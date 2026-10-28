from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from pr_radar.models import CheckState, Comment, JiraIssue, Mergeable, PullRequest, ReviewDecision, ReviewThread


class IssueKind(StrEnum):
    REVIEW_REQUESTED = "review_requested"
    CHANGES_REQUESTED = "changes_requested"
    UNREPLIED_COMMENTS = "unreplied_comments"
    CI_FAILED = "ci_failed"
    MERGE_CONFLICT = "merge_conflict"
    READY_TO_MERGE = "ready_to_merge"
    DRAFT = "draft"
    WAITING_FOR_REVIEW = "waiting_for_review"


class Bucket(StrEnum):
    NEEDS_YOU = "needs_you"
    EASY_WIN = "easy_win"
    WAITING = "waiting"


class Role(StrEnum):
    MINE = "mine"
    REVIEW = "review"


class IssueRule(BaseModel):
    priority: int
    bucket: Bucket
    template: str
    realert: bool


ISSUE_RULES: dict[IssueKind, IssueRule] = {
    IssueKind.REVIEW_REQUESTED: IssueRule(
        priority=1, bucket=Bucket.NEEDS_YOU, template="Review this PR for {author}", realert=True
    ),
    IssueKind.CHANGES_REQUESTED: IssueRule(
        priority=2, bucket=Bucket.NEEDS_YOU, template="Make the changes {people} asked for", realert=True
    ),
    IssueKind.UNREPLIED_COMMENTS: IssueRule(
        priority=3, bucket=Bucket.NEEDS_YOU, template="Reply to {count} comment(s) from {people}", realert=True
    ),
    IssueKind.CI_FAILED: IssueRule(
        priority=4, bucket=Bucket.NEEDS_YOU, template="Fix the failing checks", realert=True
    ),
    IssueKind.MERGE_CONFLICT: IssueRule(
        priority=5, bucket=Bucket.NEEDS_YOU, template="Fix the merge conflict", realert=True
    ),
    IssueKind.READY_TO_MERGE: IssueRule(
        priority=6, bucket=Bucket.EASY_WIN, template="Merge it. It is approved", realert=False
    ),
    IssueKind.DRAFT: IssueRule(
        priority=7, bucket=Bucket.NEEDS_YOU, template="Finish the draft and mark it ready for review", realert=False
    ),
    IssueKind.WAITING_FOR_REVIEW: IssueRule(
        priority=8, bucket=Bucket.WAITING, template="Wait for a review, or ask someone to review it", realert=False
    ),
}

_FAILED_CHECK_STATES = {CheckState.FAILURE, CheckState.ERROR}
_UNFINISHED_CHECK_STATES = {CheckState.FAILURE, CheckState.ERROR, CheckState.PENDING, CheckState.EXPECTED}


class Issue(BaseModel):
    kind: IssueKind
    text: str


class PrView(BaseModel):
    id: str
    number: int
    title: str
    url: str
    repo: str
    author: str
    role: Role
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    review_decision: ReviewDecision | None
    mergeable: Mergeable
    check_state: CheckState | None
    issues: list[Issue]
    bucket: Bucket
    next_action: str
    waiting_comments: list[Comment]
    days_idle: int
    is_stale: bool
    jira: list[JiraIssue]

    @property
    def top_issue(self) -> IssueKind:
        return self.issues[0].kind


def is_bot(login: str) -> bool:
    return login.endswith("[bot]")


def _is_other_person(login: str, me: str) -> bool:
    return login != me and not is_bot(login)


def conversation_comments(pr: PullRequest) -> list[Comment]:
    """Top-level PR comments plus review summaries that have text. Inline code comments live in threads."""
    items = list(pr.comments)
    for review in pr.reviews:
        if review.body.strip() and review.submitted_at:
            items.append(
                Comment(id=review.id, author=review.author, body=review.body, created_at=review.submitted_at, url=review.url)
            )
    return sorted(items, key=lambda comment: comment.created_at)


def all_comments(pr: PullRequest) -> list[Comment]:
    thread_comments = [comment for thread in pr.threads for comment in thread.comments]
    return conversation_comments(pr) + thread_comments


def unreplied_threads(pr: PullRequest, me: str) -> list[ReviewThread]:
    """Open code-comment threads where someone else spoke last."""
    waiting: list[ReviewThread] = []
    for thread in pr.threads:
        if thread.is_resolved or not thread.comments:
            continue
        last_author = thread.comments[-1].author
        if _is_other_person(last_author, me):
            waiting.append(thread)
    return waiting


def unanswered_conversation_comments(pr: PullRequest, me: str) -> list[Comment]:
    """Conversation comments from others that came after my last conversation comment."""
    conversation = conversation_comments(pr)
    my_times = [comment.created_at for comment in conversation if comment.author == me]
    my_last_reply = max(my_times) if my_times else None
    unanswered: list[Comment] = []
    for comment in conversation:
        is_after_my_reply = my_last_reply is None or comment.created_at > my_last_reply
        if _is_other_person(comment.author, me) and is_after_my_reply:
            unanswered.append(comment)
    return unanswered


def comments_waiting_on_me(pr: PullRequest, me: str) -> list[Comment]:
    thread_tails = [thread.comments[-1] for thread in unreplied_threads(pr, me)]
    return sorted(thread_tails + unanswered_conversation_comments(pr, me), key=lambda comment: comment.created_at)


def _people(logins: list[str]) -> str:
    unique: list[str] = []
    for login in logins:
        if login not in unique:
            unique.append(login)
    return ", ".join(unique)


def _issue(kind: IssueKind, **details: str | int) -> Issue:
    return Issue(kind=kind, text=ISSUE_RULES[kind].template.format(**details))


def _reviewers_requesting_changes(pr: PullRequest) -> list[str]:
    latest_state_by_reviewer: dict[str, str] = {}
    for review in pr.reviews:
        if review.state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest_state_by_reviewer[review.author] = review.state
    return [reviewer for reviewer, state in latest_state_by_reviewer.items() if state == "CHANGES_REQUESTED"]


def _is_ready_to_merge(pr: PullRequest) -> bool:
    return (
        not pr.is_draft
        and pr.review_decision == ReviewDecision.APPROVED
        and pr.mergeable != Mergeable.CONFLICTING
        and pr.check_state not in _UNFINISHED_CHECK_STATES
    )


def my_pr_issues(pr: PullRequest, me: str) -> list[Issue]:
    issues: list[Issue] = []
    if pr.review_decision == ReviewDecision.CHANGES_REQUESTED:
        issues.append(_issue(IssueKind.CHANGES_REQUESTED, people=_people(_reviewers_requesting_changes(pr)) or "a reviewer"))
    waiting = comments_waiting_on_me(pr, me)
    if waiting:
        issues.append(_issue(IssueKind.UNREPLIED_COMMENTS, count=len(waiting), people=_people([comment.author for comment in waiting])))
    if pr.check_state in _FAILED_CHECK_STATES:
        issues.append(_issue(IssueKind.CI_FAILED))
    if pr.mergeable == Mergeable.CONFLICTING:
        issues.append(_issue(IssueKind.MERGE_CONFLICT))
    if _is_ready_to_merge(pr):
        issues.append(_issue(IssueKind.READY_TO_MERGE))
    if pr.is_draft:
        issues.append(_issue(IssueKind.DRAFT))
    if not issues:
        issues.append(_issue(IssueKind.WAITING_FOR_REVIEW))
    return sorted(issues, key=lambda issue: ISSUE_RULES[issue.kind].priority)


def days_between(earlier: datetime, later: datetime) -> int:
    return max(0, (later - earlier).days)


def _build_view(
    pr: PullRequest,
    role: Role,
    issues: list[Issue],
    waiting_comments: list[Comment],
    now: datetime,
    stale_days: int,
    jira: list[JiraIssue],
) -> PrView:
    days_idle = days_between(pr.updated_at, now)
    return PrView(
        id=pr.id,
        number=pr.number,
        title=pr.title,
        url=pr.url,
        repo=pr.repo,
        author=pr.author,
        role=role,
        is_draft=pr.is_draft,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        review_decision=pr.review_decision,
        mergeable=pr.mergeable,
        check_state=pr.check_state,
        issues=issues,
        bucket=ISSUE_RULES[issues[0].kind].bucket,
        next_action=issues[0].text,
        waiting_comments=waiting_comments,
        days_idle=days_idle,
        is_stale=days_idle >= stale_days,
        jira=jira,
    )


def analyze_my_pr(pr: PullRequest, me: str, now: datetime, stale_days: int, jira: list[JiraIssue]) -> PrView:
    return _build_view(pr, Role.MINE, my_pr_issues(pr, me), comments_waiting_on_me(pr, me), now, stale_days, jira)


def analyze_review_request(pr: PullRequest, now: datetime, stale_days: int, jira: list[JiraIssue]) -> PrView:
    issues = [_issue(IssueKind.REVIEW_REQUESTED, author=pr.author)]
    return _build_view(pr, Role.REVIEW, issues, [], now, stale_days, jira)


def sort_views(views: list[PrView]) -> list[PrView]:
    bucket_order = {Bucket.NEEDS_YOU: 0, Bucket.EASY_WIN: 1, Bucket.WAITING: 2}
    return sorted(
        views,
        key=lambda view: (bucket_order[view.bucket], ISSUE_RULES[view.top_issue].priority, -view.days_idle),
    )

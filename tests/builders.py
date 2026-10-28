from datetime import datetime, timedelta, timezone

from pr_radar.models import CheckState, Comment, Mergeable, PullRequest, Review, ReviewDecision, ReviewThread

NOW = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
ME = "me"


def at(minutes_ago: int) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def comment(comment_id: str, author: str, minutes_ago: int, body: str = "Looks good") -> Comment:
    return Comment(id=comment_id, author=author, body=body, created_at=at(minutes_ago), url=f"https://example.test/{comment_id}")


def thread(thread_id: str, comments: list[Comment], is_resolved: bool = False) -> ReviewThread:
    return ReviewThread(id=thread_id, is_resolved=is_resolved, comments=comments)


def review(review_id: str, author: str, state: str, minutes_ago: int, body: str = "") -> Review:
    return Review(id=review_id, author=author, state=state, body=body, submitted_at=at(minutes_ago), url=f"https://example.test/{review_id}")


def pull_request(
    pr_id: str = "PR_1",
    author: str = ME,
    is_draft: bool = False,
    updated_minutes_ago: int = 10,
    review_decision: ReviewDecision | None = ReviewDecision.REVIEW_REQUIRED,
    mergeable: Mergeable = Mergeable.MERGEABLE,
    check_state: CheckState | None = CheckState.SUCCESS,
    comments: list[Comment] | None = None,
    reviews: list[Review] | None = None,
    threads: list[ReviewThread] | None = None,
    title: str = "Add login page",
    head_ref: str = "feature/login",
) -> PullRequest:
    return PullRequest(
        id=pr_id,
        number=7,
        title=title,
        url=f"https://example.test/pr/{pr_id}",
        repo="acme/web",
        author=author,
        is_draft=is_draft,
        created_at=at(60 * 24 * 10),
        updated_at=at(updated_minutes_ago),
        head_ref=head_ref,
        review_decision=review_decision,
        mergeable=mergeable,
        check_state=check_state,
        comments=comments or [],
        reviews=reviews or [],
        threads=threads or [],
    )

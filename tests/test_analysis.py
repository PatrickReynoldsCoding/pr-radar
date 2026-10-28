from builders import ME, NOW, comment, pull_request, review, thread

from pr_radar.analysis import (
    Bucket,
    IssueKind,
    analyze_my_pr,
    analyze_review_request,
    comments_waiting_on_me,
    sort_views,
    unanswered_conversation_comments,
    unreplied_threads,
)
from pr_radar.models import CheckState, Mergeable, ReviewDecision


def kinds(view):
    return [issue.kind for issue in view.issues]


def test_thread_where_someone_else_spoke_last_is_unreplied():
    pr = pull_request(threads=[thread("T1", [comment("C1", ME, 30), comment("C2", "sam", 20)])])
    assert [waiting.id for waiting in unreplied_threads(pr, ME)] == ["T1"]


def test_thread_where_i_spoke_last_or_resolved_is_not_unreplied():
    pr = pull_request(
        threads=[
            thread("T1", [comment("C1", "sam", 30), comment("C2", ME, 20)]),
            thread("T2", [comment("C3", "sam", 30)], is_resolved=True),
        ]
    )
    assert unreplied_threads(pr, ME) == []


def test_bot_comments_never_wait_on_me():
    pr = pull_request(
        comments=[comment("C1", "ci-helper[bot]", 5)],
        threads=[thread("T1", [comment("C2", "linter[bot]", 5)])],
    )
    assert comments_waiting_on_me(pr, ME) == []


def test_conversation_comments_after_my_last_reply_are_unanswered():
    pr = pull_request(comments=[comment("C1", "sam", 50), comment("C2", ME, 40), comment("C3", "kim", 30)])
    assert [waiting.id for waiting in unanswered_conversation_comments(pr, ME)] == ["C3"]


def test_review_summary_with_text_counts_as_a_comment():
    pr = pull_request(reviews=[review("R1", "sam", "COMMENTED", 15, body="Why this approach?")])
    assert [waiting.id for waiting in unanswered_conversation_comments(pr, ME)] == ["R1"]


def test_unreplied_comments_give_reply_next_action():
    pr = pull_request(threads=[thread("T1", [comment("C1", "sam", 20)]), thread("T2", [comment("C2", "kim", 10)])])
    view = analyze_my_pr(pr, ME, NOW, stale_days=3, jira=[])
    assert view.bucket == Bucket.NEEDS_YOU
    assert view.next_action == "Reply to 2 comment(s) from sam, kim"


def test_changes_requested_comes_before_other_problems():
    pr = pull_request(
        review_decision=ReviewDecision.CHANGES_REQUESTED,
        reviews=[review("R1", "sam", "CHANGES_REQUESTED", 30)],
        check_state=CheckState.FAILURE,
        mergeable=Mergeable.CONFLICTING,
    )
    view = analyze_my_pr(pr, ME, NOW, stale_days=3, jira=[])
    assert kinds(view) == [IssueKind.CHANGES_REQUESTED, IssueKind.CI_FAILED, IssueKind.MERGE_CONFLICT]
    assert view.next_action == "Make the changes sam asked for"


def test_approved_with_green_checks_is_an_easy_win():
    view = analyze_my_pr(pull_request(review_decision=ReviewDecision.APPROVED), ME, NOW, stale_days=3, jira=[])
    assert view.bucket == Bucket.EASY_WIN
    assert kinds(view) == [IssueKind.READY_TO_MERGE]


def test_approved_but_failing_checks_is_not_ready():
    pr = pull_request(review_decision=ReviewDecision.APPROVED, check_state=CheckState.FAILURE)
    view = analyze_my_pr(pr, ME, NOW, stale_days=3, jira=[])
    assert kinds(view) == [IssueKind.CI_FAILED]


def test_no_problems_means_waiting_for_review():
    view = analyze_my_pr(pull_request(), ME, NOW, stale_days=3, jira=[])
    assert view.bucket == Bucket.WAITING
    assert kinds(view) == [IssueKind.WAITING_FOR_REVIEW]


def test_old_activity_is_stale():
    view = analyze_my_pr(pull_request(updated_minutes_ago=60 * 24 * 4), ME, NOW, stale_days=3, jira=[])
    assert view.days_idle == 4
    assert view.is_stale


def test_review_request_needs_me():
    view = analyze_review_request(pull_request(author="sam"), NOW, stale_days=3, jira=[])
    assert view.bucket == Bucket.NEEDS_YOU
    assert view.next_action == "Review this PR for sam"


def test_sort_puts_needs_you_first_then_easy_wins():
    waiting = analyze_my_pr(pull_request(pr_id="A"), ME, NOW, 3, [])
    easy = analyze_my_pr(pull_request(pr_id="B", review_decision=ReviewDecision.APPROVED), ME, NOW, 3, [])
    urgent = analyze_my_pr(pull_request(pr_id="C", check_state=CheckState.FAILURE), ME, NOW, 3, [])
    assert [view.id for view in sort_views([waiting, easy, urgent])] == ["C", "B", "A"]

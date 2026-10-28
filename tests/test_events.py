from datetime import date, datetime, time, timedelta

from builders import ME, NOW, comment, pull_request, thread

from pr_radar.analysis import analyze_my_pr, analyze_review_request
from pr_radar.config import AlertConfig
from pr_radar.events import (
    EventKind,
    TrackedPr,
    detect_events,
    due_reminders,
    is_morning_summary_due,
    is_work_time,
    prune_alert_times,
    snapshot_of,
)
from pr_radar.models import CheckState, ReviewDecision


def mine(pr):
    return TrackedPr(view=analyze_my_pr(pr, ME, NOW, 3, []), pr=pr)


def review_request(pr):
    return TrackedPr(view=analyze_review_request(pr, NOW, 3, []), pr=pr)


def snapshots(tracked_prs):
    return {tracked.view.id: snapshot_of(tracked) for tracked in tracked_prs}


def event_kinds(events):
    return [event.kind for event in events]


def test_first_check_is_only_a_baseline():
    assert detect_events(None, [mine(pull_request(check_state=CheckState.FAILURE))], ME, NOW) == []


def test_new_comment_from_someone_else_is_an_event():
    before = mine(pull_request(threads=[thread("T1", [comment("C1", ME, 30)])]))
    after = mine(pull_request(threads=[thread("T1", [comment("C1", ME, 30), comment("C2", "sam", 1, body="Can you\nrename this?")])]))
    events = detect_events(snapshots([before]), [after], ME, NOW)
    assert event_kinds(events) == [EventKind.NEW_COMMENT]
    assert events[0].message == 'sam: "Can you rename this?"'
    assert events[0].url == "https://example.test/C2"


def test_my_own_new_comment_is_not_an_event():
    before = mine(pull_request())
    after = mine(pull_request(comments=[comment("C1", ME, 1)]))
    assert detect_events(snapshots([before]), [after], ME, NOW) == []


def test_several_new_comments_make_one_event():
    before = mine(pull_request())
    after = mine(pull_request(comments=[comment("C1", "sam", 3), comment("C2", "kim", 2), comment("C3", "sam", 1)]))
    events = detect_events(snapshots([before]), [after], ME, NOW)
    assert [event.message for event in events] == ["3 new comments from sam, kim"]


def test_new_problems_are_events_but_old_ones_are_not():
    before = mine(pull_request(check_state=CheckState.FAILURE))
    after = mine(pull_request(check_state=CheckState.FAILURE, review_decision=ReviewDecision.CHANGES_REQUESTED))
    assert event_kinds(detect_events(snapshots([before]), [after], ME, NOW)) == [EventKind.CHANGES_REQUESTED]


def test_becoming_approved_is_a_ready_to_merge_event():
    before = mine(pull_request())
    after = mine(pull_request(review_decision=ReviewDecision.APPROVED))
    assert event_kinds(detect_events(snapshots([before]), [after], ME, NOW)) == [EventKind.READY_TO_MERGE]


def test_new_review_request_is_an_event():
    events = detect_events({}, [review_request(pull_request(pr_id="R1", author="sam"))], ME, NOW)
    assert event_kinds(events) == [EventKind.REVIEW_REQUESTED]
    assert events[0].message == "sam asked you to review"


def test_going_stale_is_an_event_once():
    before = mine(pull_request(updated_minutes_ago=60 * 24 * 2))
    after = mine(pull_request(updated_minutes_ago=60 * 24 * 3))
    assert event_kinds(detect_events(snapshots([before]), [after], ME, NOW)) == [EventKind.STALE]
    assert detect_events(snapshots([after]), [after], ME, NOW) == []


def test_reminder_is_due_when_never_alerted_or_after_wait():
    failing = mine(pull_request(pr_id="A", check_state=CheckState.FAILURE)).view
    assert due_reminders([failing], {}, {}, NOW, 30) == [failing]
    assert due_reminders([failing], {"A": NOW - timedelta(minutes=10)}, {}, NOW, 30) == []
    assert due_reminders([failing], {"A": NOW - timedelta(minutes=31)}, {}, NOW, 30) == [failing]


def test_snoozed_and_waiting_prs_get_no_reminder():
    failing = mine(pull_request(pr_id="A", check_state=CheckState.FAILURE)).view
    waiting = mine(pull_request(pr_id="B")).view
    snoozes = {"A": NOW + timedelta(hours=1)}
    assert due_reminders([failing, waiting], {}, snoozes, NOW, 30) == []


def test_prune_forgets_prs_that_no_longer_need_me():
    fixed = mine(pull_request(pr_id="A")).view
    assert prune_alert_times([fixed], {"A": NOW, "GONE": NOW}) == {}


def test_work_time_respects_days_and_hours():
    alerts = AlertConfig(work_days=[0, 1, 2, 3, 4], work_start=time(9), work_end=time(18))
    wednesday = datetime(2026, 3, 4, 10, 0)
    assert is_work_time(wednesday, alerts)
    assert not is_work_time(wednesday.replace(hour=19), alerts)
    assert not is_work_time(datetime(2026, 3, 7, 10, 0), alerts)


def test_morning_summary_is_due_once_a_day():
    alerts = AlertConfig(morning_summary_at=time(9, 15))
    morning = datetime(2026, 3, 4, 9, 20)
    assert is_morning_summary_due(morning, None, alerts)
    assert not is_morning_summary_due(morning, date(2026, 3, 4), alerts)
    assert not is_morning_summary_due(morning.replace(minute=0), None, alerts)

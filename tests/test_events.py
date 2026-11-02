from datetime import date, datetime, time, timedelta

from builders import ME, NOW, comment, pull_request, thread

from pr_radar.analysis import analyze_my_pr, analyze_review_request
from pr_radar.config import AlertConfig
from pr_radar.events import (
    EventKind,
    TrackedPr,
    detect_events,
    due_quiet_alerts,
    due_reminders,
    is_morning_summary_due,
    is_work_time,
    prune_alert_times,
    prune_quiet_alerts,
    snapshot_of,
)
from pr_radar.models import CheckState, ReviewDecision
from pr_radar.reminders import ReminderSettings


def mine(pr):
    return TrackedPr(view=analyze_my_pr(pr, ME, NOW, 3, []), pr=pr)


def review_request(pr):
    return TrackedPr(view=analyze_review_request(pr, NOW, 3, []), pr=pr)


def quiet(pr_id, days):
    return mine(pull_request(pr_id=pr_id, updated_minutes_ago=60 * 24 * days)).view


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


def test_going_quiet_is_not_a_change_event():
    before = mine(pull_request(updated_minutes_ago=60 * 24 * 2))
    after = mine(pull_request(updated_minutes_ago=60 * 24 * 3))
    assert detect_events(snapshots([before]), [after], ME, NOW) == []


def test_quiet_alert_is_due_once_per_quiet_period():
    assert due_quiet_alerts([quiet("A", 3)], {}, {}, NOW) == [quiet("A", 3)]
    assert due_quiet_alerts([quiet("A", 5)], {"A": 1}, {}, NOW) == []
    assert due_quiet_alerts([quiet("A", 6)], {"A": 1}, {}, NOW) == [quiet("A", 6)]


def test_active_and_snoozed_prs_get_no_quiet_alert():
    assert due_quiet_alerts([quiet("A", 2)], {}, {}, NOW) == []
    assert due_quiet_alerts([quiet("A", 3)], {}, {"A": NOW + timedelta(hours=1)}, NOW) == []


def test_pr_that_changed_while_radar_was_off_alerts_again():
    assert due_quiet_alerts([quiet("A", 3)], {"A": 2}, {}, NOW) == [quiet("A", 3)]


def test_prune_quiet_forgets_prs_with_new_activity_or_closed():
    assert prune_quiet_alerts([quiet("A", 1), quiet("B", 4)], {"A": 1, "B": 1, "GONE": 1}) == {"B": 1}


def test_reminder_is_due_when_never_alerted_or_after_wait():
    failing = mine(pull_request(pr_id="A", check_state=CheckState.FAILURE)).view
    settings = ReminderSettings(ci_failed_days=2)
    assert due_reminders([failing], {}, {}, NOW, settings) == [failing]
    assert due_reminders([failing], {"A": NOW - timedelta(days=1)}, {}, NOW, settings) == []
    assert due_reminders([failing], {"A": NOW - timedelta(days=2)}, {}, NOW, settings) == [failing]


def test_each_problem_uses_its_own_reminder_time():
    draft = mine(pull_request(pr_id="D", is_draft=True)).view
    approved = mine(pull_request(pr_id="E", review_decision=ReviewDecision.APPROVED)).view
    one_and_a_half_days_ago = {"D": NOW - timedelta(hours=36), "E": NOW - timedelta(hours=36)}
    due = due_reminders([draft, approved], one_and_a_half_days_ago, {}, NOW, ReminderSettings(draft_days=2, ready_to_merge_days=1))
    assert due == [approved]


def test_snoozed_and_waiting_prs_get_no_reminder():
    failing = mine(pull_request(pr_id="A", check_state=CheckState.FAILURE)).view
    waiting = mine(pull_request(pr_id="B")).view
    snoozes = {"A": NOW + timedelta(hours=1)}
    assert due_reminders([failing, waiting], {}, snoozes, NOW, ReminderSettings()) == []


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

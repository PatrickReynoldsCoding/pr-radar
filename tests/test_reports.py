from datetime import date, timedelta

from builders import ME, NOW, comment, pull_request, thread

from pr_radar.analysis import analyze_my_pr, analyze_review_request
from pr_radar.jira import find_issue_keys
from pr_radar.models import CheckState, ReviewDecision, ShippedPr, WeeklyActivity
from pr_radar.reports import menubar_text, morning_message, reminder_message, summarize, weekly_report_markdown


def views():
    return [
        analyze_my_pr(pull_request(pr_id="A", threads=[thread("T1", [comment("C1", "sam", 5)])]), ME, NOW, 3, []),
        analyze_my_pr(pull_request(pr_id="B", review_decision=ReviewDecision.APPROVED, title="Fix | pipe"), ME, NOW, 3, []),
        analyze_my_pr(pull_request(pr_id="C", check_state=CheckState.FAILURE), ME, NOW, 3, []),
        analyze_review_request(pull_request(pr_id="D", author="kim"), NOW, 3, []),
    ]


def test_summary_counts_each_pr_once():
    summary = summarize(views())
    assert (summary.to_reply, summary.to_review, summary.to_fix, summary.ready_to_merge) == (1, 1, 1, 1)
    assert summary.needs_you == 3


def test_morning_message_lists_only_non_zero_counts():
    assert morning_message(summarize(views())) == (
        "Today: 1 PR(s) with comments to reply to, 1 review(s) to do, 1 PR(s) to fix, 1 ready to merge."
    )
    assert morning_message(summarize([])) == "Nothing needs you right now. Good start!"


def test_reminder_message_for_many_prs_is_short():
    many = [views()[0]] * 5
    assert reminder_message(many).splitlines()[-1] == "…and 2 more"


def test_menubar_shows_count_and_escapes_pipes():
    text = menubar_text(views(), None, None, "http://127.0.0.1:4747/", NOW)
    lines = text.splitlines()
    assert lines[0] == "🔔 3"
    assert "Fix / pipe" in text
    assert all(line.count("|") <= 1 for line in lines)


def test_menubar_shows_focus_minutes_left():
    text = menubar_text(views(), NOW + timedelta(minutes=24, seconds=30), None, "http://127.0.0.1:4747/", NOW)
    assert text.splitlines()[0] == "🎯 25m"


def test_weekly_report_lists_merged_reviewed_and_open():
    shipped = ShippedPr(number=3, title="Speed up search", url="https://example.test/3", repo="acme/web", at=NOW)
    activity = WeeklyActivity(merged=[shipped], opened=[], reviewed=[])
    report = weekly_report_markdown(activity, views(), date(2026, 2, 25), date(2026, 3, 4))
    assert "**Merged (1)**\n- [acme/web#3](https://example.test/3) Speed up search" in report
    assert "**Opened (0)**\n- None" in report
    assert "**Still open (3)**" in report


def test_jira_keys_come_from_title_and_branch():
    assert find_issue_keys(["ABC-12 Add login", "feature/abc-12-login", "xyz-9"], []) == ["ABC-12", "XYZ-9"]
    assert find_issue_keys(["Use UTF-8 for ABC-3"], ["ABC"]) == ["ABC-3"]

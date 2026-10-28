from datetime import date, datetime

from pydantic import BaseModel

from pr_radar.analysis import Bucket, IssueKind, PrView, Role
from pr_radar.models import ShippedPr, WeeklyActivity
from pr_radar.sync import MENUBAR_SPEED_CHOICES

_MENUBAR_TITLE_MAX = 60


class Summary(BaseModel):
    to_reply: int
    to_review: int
    to_fix: int
    ready_to_merge: int
    waiting: int
    stale: int

    @property
    def needs_you(self) -> int:
        return self.to_reply + self.to_review + self.to_fix


_FIX_KINDS = {IssueKind.CHANGES_REQUESTED, IssueKind.CI_FAILED, IssueKind.MERGE_CONFLICT, IssueKind.DRAFT}


def summarize(views: list[PrView]) -> Summary:
    to_reply = to_review = to_fix = ready = waiting = stale = 0
    for view in views:
        kinds = {issue.kind for issue in view.issues}
        if view.role == Role.REVIEW:
            to_review += 1
        elif IssueKind.UNREPLIED_COMMENTS in kinds:
            to_reply += 1
        elif kinds & _FIX_KINDS:
            to_fix += 1
        elif view.bucket == Bucket.EASY_WIN:
            ready += 1
        else:
            waiting += 1
        if view.is_stale and view.role == Role.MINE:
            stale += 1
    return Summary(
        to_reply=to_reply, to_review=to_review, to_fix=to_fix, ready_to_merge=ready, waiting=waiting, stale=stale
    )


_SUMMARY_PARTS: list[tuple[str, str]] = [
    ("to_reply", "{count} PR(s) with comments to reply to"),
    ("to_review", "{count} review(s) to do"),
    ("to_fix", "{count} PR(s) to fix"),
    ("ready_to_merge", "{count} ready to merge"),
]


def summary_lines(summary: Summary) -> list[str]:
    lines: list[str] = []
    for field, template in _SUMMARY_PARTS:
        count = getattr(summary, field)
        if count:
            lines.append(template.format(count=count))
    return lines


def morning_message(summary: Summary) -> str:
    lines = summary_lines(summary)
    if not lines:
        return "Nothing needs you right now. Good start!"
    return "Today: " + ", ".join(lines) + "."


def reminder_message(due: list[PrView]) -> str:
    if len(due) == 1:
        return f"{due[0].next_action}: {due[0].title}"
    first_actions = [f"• {view.next_action}" for view in due[:3]]
    more = [f"…and {len(due) - 3} more"] if len(due) > 3 else []
    return "\n".join(first_actions + more)


def _shipped_lines(prs: list[ShippedPr]) -> list[str]:
    if not prs:
        return ["- None"]
    return [f"- [{pr.repo}#{pr.number}]({pr.url}) {pr.title}" for pr in sorted(prs, key=lambda pr: pr.at)]


def weekly_report_markdown(activity: WeeklyActivity, open_views: list[PrView], since: date, today: date) -> str:
    my_open = [view for view in open_views if view.role == Role.MINE]
    lines = [
        f"## What I shipped: {since.isoformat()} to {today.isoformat()}",
        "",
        f"**Merged ({len(activity.merged)})**",
        *_shipped_lines(activity.merged),
        "",
        f"**Reviewed for others ({len(activity.reviewed)})**",
        *_shipped_lines(activity.reviewed),
        "",
        f"**Opened ({len(activity.opened)})**",
        *_shipped_lines(activity.opened),
        "",
        f"**Still open ({len(my_open)})**",
    ]
    if not my_open:
        lines.append("- None")
    for view in my_open:
        lines.append(f"- [{view.repo}#{view.number}]({view.url}) {view.title}: {view.next_action}")
    return "\n".join(lines) + "\n"


def _menubar_safe(text: str) -> str:
    # SwiftBar reads "|" as the start of its options, so it must not appear in a title.
    one_line = " ".join(text.split()).replace("|", "/")
    return one_line if len(one_line) <= _MENUBAR_TITLE_MAX else one_line[: _MENUBAR_TITLE_MAX - 1] + "…"


def _speed_label(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds >= 60 and seconds % 60 == 0 else f"{seconds} s"


def _curl_action(label: str, method: str, url: str) -> str:
    return (
        f"{label} | bash=/usr/bin/curl param1=-s param2=-H param3=X-PR-Radar:1 param4=-X param5={method} "
        f"param6={url} terminal=false refresh=true"
    )


def _sync_lines(dashboard_url: str, light_check_seconds: int) -> list[str]:
    lines = [
        _curl_action("🔄 Sync now", "POST", f"{dashboard_url}api/refresh"),
        f"Sync speed: every {_speed_label(light_check_seconds)}",
    ]
    for seconds in MENUBAR_SPEED_CHOICES:
        tick = " ✓" if seconds == light_check_seconds else ""
        url = f"{dashboard_url}api/settings/sync?light_check_seconds={seconds}"
        lines.append("--" + _curl_action(f"Every {_speed_label(seconds)}{tick}", "POST", url))
    return lines


def menubar_text(
    views: list[PrView],
    focus_until: datetime | None,
    error: str | None,
    dashboard_url: str,
    light_check_seconds: int,
    now: datetime,
) -> str:
    summary = summarize(views)
    if error:
        title = "⚠️ PR"
    elif focus_until and focus_until > now:
        minutes_left = int((focus_until - now).total_seconds() // 60) + 1
        title = f"🎯 {minutes_left}m"
    elif summary.needs_you:
        title = f"🔔 {summary.needs_you}"
    elif summary.ready_to_merge:
        title = f"🚀 {summary.ready_to_merge}"
    else:
        title = "✅"
    lines = [title, "---", f"Open PR Radar | href={dashboard_url}"]
    if error:
        lines.append(f"Error: {_menubar_safe(error)}")
    for view in views:
        if view.bucket == Bucket.WAITING:
            continue
        icon = "🚀" if view.bucket == Bucket.EASY_WIN else "🔴"
        lines.append(f"{icon} {_menubar_safe(view.next_action)} | href={view.url}")
        lines.append(f"--{_menubar_safe(view.repo + '#' + str(view.number) + ' ' + view.title)} | href={view.url}")
    lines.append("---")
    lines.extend(_sync_lines(dashboard_url, light_check_seconds))
    lines.append("---")
    focus_url = f"{dashboard_url}api/focus"
    for minutes in (25, 50):
        lines.append(_curl_action(f"Focus {minutes} min", "POST", f"{focus_url}?minutes={minutes}"))
    if focus_until and focus_until > now:
        lines.append(_curl_action("End focus", "DELETE", focus_url))
    return "\n".join(lines) + "\n"

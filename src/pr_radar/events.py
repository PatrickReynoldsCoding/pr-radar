from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from pr_radar.analysis import ISSUE_RULES, IssueKind, PrView, Role, all_comments, is_bot
from pr_radar.config import AlertConfig
from pr_radar.models import Comment, PullRequest
from pr_radar.reminders import ReminderSettings, reminder_wait

_EXCERPT_LENGTH = 140


class EventKind(StrEnum):
    NEW_COMMENT = "new_comment"
    CHANGES_REQUESTED = "changes_requested"
    CI_FAILED = "ci_failed"
    MERGE_CONFLICT = "merge_conflict"
    READY_TO_MERGE = "ready_to_merge"
    REVIEW_REQUESTED = "review_requested"
    STALE = "stale"


_EVENT_FOR_NEW_ISSUE: dict[IssueKind, tuple[EventKind, str]] = {
    IssueKind.CHANGES_REQUESTED: (EventKind.CHANGES_REQUESTED, "Changes requested"),
    IssueKind.CI_FAILED: (EventKind.CI_FAILED, "Checks failed"),
    IssueKind.MERGE_CONFLICT: (EventKind.MERGE_CONFLICT, "Merge conflict"),
    IssueKind.READY_TO_MERGE: (EventKind.READY_TO_MERGE, "Approved. Ready to merge"),
}


class PrSnapshot(BaseModel):
    role: Role
    issue_kinds: list[IssueKind]
    comment_ids: list[str]


class Event(BaseModel):
    id: str
    kind: EventKind
    pr_id: str
    repo: str
    pr_title: str
    url: str
    message: str
    created_at: datetime
    read: bool


class TrackedPr(BaseModel):
    view: PrView
    pr: PullRequest


def snapshot_of(tracked: TrackedPr) -> PrSnapshot:
    return PrSnapshot(
        role=tracked.view.role,
        issue_kinds=[issue.kind for issue in tracked.view.issues],
        comment_ids=[comment.id for comment in all_comments(tracked.pr)],
    )


def excerpt(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= _EXCERPT_LENGTH:
        return one_line
    return one_line[: _EXCERPT_LENGTH - 1] + "…"


def _event(view: PrView, kind: EventKind, message: str, url: str, now: datetime, suffix: str = "") -> Event:
    return Event(
        id=f"{kind}:{view.id}:{now.isoformat()}{suffix}",
        kind=kind,
        pr_id=view.id,
        repo=view.repo,
        pr_title=view.title,
        url=url,
        message=message,
        created_at=now,
        read=False,
    )


def _new_comment_message(new_comments: list[Comment]) -> str:
    if len(new_comments) == 1:
        only = new_comments[0]
        return f'{only.author}: "{excerpt(only.body)}"'
    authors: list[str] = []
    for comment in new_comments:
        if comment.author not in authors:
            authors.append(comment.author)
    return f"{len(new_comments)} new comments from {', '.join(authors)}"


def _new_comment_events(before: PrSnapshot, tracked: TrackedPr, me: str, now: datetime) -> list[Event]:
    seen_ids = set(before.comment_ids)
    new_comments: list[Comment] = []
    for comment in all_comments(tracked.pr):
        is_new = comment.id not in seen_ids
        if is_new and comment.author != me and not is_bot(comment.author):
            new_comments.append(comment)
    if not new_comments:
        return []
    new_comments.sort(key=lambda comment: comment.created_at)
    latest = new_comments[-1]
    return [_event(tracked.view, EventKind.NEW_COMMENT, _new_comment_message(new_comments), latest.url, now, f":{latest.id}")]


def _new_issue_events(before: PrSnapshot, view: PrView, now: datetime) -> list[Event]:
    events: list[Event] = []
    for issue in view.issues:
        is_new = issue.kind not in before.issue_kinds
        if is_new and issue.kind in _EVENT_FOR_NEW_ISSUE:
            kind, message = _EVENT_FOR_NEW_ISSUE[issue.kind]
            events.append(_event(view, kind, message, view.url, now))
    return events


def detect_events(
    previous: dict[str, PrSnapshot] | None, current: list[TrackedPr], me: str, now: datetime
) -> list[Event]:
    """Finds what changed since the last check. The first check only records a baseline, so it alerts nothing."""
    if previous is None:
        return []
    events: list[Event] = []
    for tracked in current:
        view = tracked.view
        before = previous.get(view.id)
        if before is None:
            if view.role == Role.REVIEW:
                events.append(_event(view, EventKind.REVIEW_REQUESTED, f"{view.author} asked you to review", view.url, now))
            continue
        events.extend(_new_comment_events(before, tracked, me, now))
        events.extend(_new_issue_events(before, view, now))
    return events


def quiet_events(views: list[PrView], now: datetime) -> list[Event]:
    return [_event(view, EventKind.STALE, f"No activity for {view.days_idle} days", view.url, now) for view in views]


def is_snoozed(pr_id: str, snoozed_until: dict[str, datetime], now: datetime) -> bool:
    until = snoozed_until.get(pr_id)
    return until is not None and until > now


def needs_realert(view: PrView) -> bool:
    return ISSUE_RULES[view.top_issue].realert


def due_reminders(
    views: list[PrView],
    last_alerted: dict[str, datetime],
    snoozed_until: dict[str, datetime],
    now: datetime,
    settings: ReminderSettings,
) -> list[PrView]:
    """PRs that still need you and have not had an alert for the time set for their problem."""
    due: list[PrView] = []
    for view in views:
        if not needs_realert(view) or is_snoozed(view.id, snoozed_until, now):
            continue
        last = last_alerted.get(view.id)
        if last is None or now - last >= reminder_wait(settings, view.top_issue):
            due.append(view)
    return due


def prune_alert_times(views: list[PrView], last_alerted: dict[str, datetime]) -> dict[str, datetime]:
    """Forgets PRs that no longer need you, so a new problem on them starts a fresh timer."""
    still_needed = {view.id for view in views if needs_realert(view)}
    return {pr_id: at for pr_id, at in last_alerted.items() if pr_id in still_needed}


def due_quiet_alerts(
    views: list[PrView], quiet_alerted: dict[str, int], snoozed_until: dict[str, datetime], now: datetime
) -> list[PrView]:
    """Quiet PRs whose quiet period changed since their last "gone quiet" alert.

    The count only goes down when the PR changed, so "changed" (not "went up") also catches a PR
    that had activity and went quiet again while PR Radar was off.
    """
    due: list[PrView] = []
    for view in views:
        is_new_period = view.quiet_periods != quiet_alerted.get(view.id)
        # A draft has its own reminder, so it does not get a second alert for the same days.
        if view.is_stale and not view.is_draft and is_new_period and not is_snoozed(view.id, snoozed_until, now):
            due.append(view)
    return due


def prune_quiet_alerts(views: list[PrView], quiet_alerted: dict[str, int]) -> dict[str, int]:
    """Forgets PRs that had activity or closed, so their next quiet period alerts again."""
    still_quiet = {view.id for view in views if view.is_stale}
    return {pr_id: periods for pr_id, periods in quiet_alerted.items() if pr_id in still_quiet}


def prune_snoozes(snoozed_until: dict[str, datetime], now: datetime) -> dict[str, datetime]:
    return {pr_id: until for pr_id, until in snoozed_until.items() if until > now}


def is_work_time(local_now: datetime, alerts: AlertConfig) -> bool:
    is_work_day = local_now.weekday() in alerts.work_days
    return is_work_day and alerts.work_start <= local_now.time() < alerts.work_end


def is_morning_summary_due(local_now: datetime, last_sent: date | None, alerts: AlertConfig) -> bool:
    already_sent_today = last_sent == local_now.date()
    return is_work_time(local_now, alerts) and local_now.time() >= alerts.morning_summary_at and not already_sent_today

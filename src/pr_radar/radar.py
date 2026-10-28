import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import httpx
from pydantic import BaseModel

from pr_radar.analysis import PrView, analyze_my_pr, analyze_review_request, sort_views
from pr_radar.config import Config
from pr_radar.events import (
    Event,
    EventKind,
    TrackedPr,
    detect_events,
    due_reminders,
    is_morning_summary_due,
    is_snoozed,
    is_work_time,
    needs_realert,
    prune_alert_times,
    prune_snoozes,
    snapshot_of,
)
from pr_radar.github import GitHubClient, GitHubError, OpenPrs
from pr_radar.jira import JiraClient, find_issue_keys
from pr_radar.models import JiraIssue, PullRequest
from pr_radar.notifier import Notifier
from pr_radar.reports import Summary, menubar_text, morning_message, reminder_message, summarize, summary_lines, weekly_report_markdown
from pr_radar.secrets import SecretError
from pr_radar.store import AppState, StateStore, keep_latest_events

logger = logging.getLogger(__name__)

_EVENT_TITLES: dict[EventKind, str] = {
    EventKind.NEW_COMMENT: "💬 New comment",
    EventKind.CHANGES_REQUESTED: "✏️ Changes requested",
    EventKind.CI_FAILED: "❌ Checks failed",
    EventKind.MERGE_CONFLICT: "⚔️ Merge conflict",
    EventKind.READY_TO_MERGE: "🚀 Ready to merge",
    EventKind.REVIEW_REQUESTED: "👀 Review requested",
    EventKind.STALE: "💤 PR has gone quiet",
}

_CHECK_ERRORS = (GitHubError, SecretError, httpx.HTTPError)


class Alert(BaseModel):
    title: str
    subtitle: str
    message: str
    url: str
    group: str


class Dashboard(BaseModel):
    login: str | None
    checked_at: datetime | None
    error: str | None
    views: list[PrView]
    summary: Summary
    summary_lines: list[str]
    events: list[Event]
    unread: int
    snoozed_until: dict[str, datetime]
    focus_until: datetime | None
    is_work_time: bool
    poll_seconds: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _short_repo(repo: str) -> str:
    return repo.split("/")[-1]


def _event_alert(event: Event) -> Alert:
    return Alert(
        title=_EVENT_TITLES[event.kind],
        subtitle=f"{_short_repo(event.repo)}: {event.pr_title}",
        message=event.message,
        url=event.url,
        group=f"pr-radar-{event.pr_id}",
    )


class Radar:
    def __init__(
        self,
        config: Config,
        github: GitHubClient,
        jira: JiraClient,
        notifier: Notifier,
        store: StateStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config
        self._clock = clock
        self._github = github
        self._jira = jira
        self._notifier = notifier
        self._store = store
        self._state: AppState = store.load()
        self._views: list[PrView] = []
        self._login: str | None = None
        self._checked_at: datetime | None = None
        self._error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self._config.port}/"

    async def run_forever(self) -> None:
        while True:
            await self.check()
            await asyncio.sleep(self._config.github.poll_seconds)

    async def check(self) -> None:
        async with self._lock:
            now = self._clock()
            try:
                open_prs = await self._github.fetch_open_prs()
            except _CHECK_ERRORS as error:
                logger.warning("GitHub check failed: %s", error)
                self._error = str(error) or type(error).__name__
                self._checked_at = now
                return
            tracked = await self._track(open_prs, now)
            views = sort_views([item.view for item in tracked])
            events = detect_events(self._state.snapshots, tracked, open_prs.login, now)
            self._state.snapshots = {item.view.id: snapshot_of(item) for item in tracked}
            self._state.events = keep_latest_events(self._state.events + events)
            self._views = views
            self._login = open_prs.login
            self._checked_at = now
            self._error = None
            self._send_alerts(events, now)
            self._store.save(self._state)

    async def _track(self, open_prs: OpenPrs, now: datetime) -> list[TrackedPr]:
        jira_by_key = await self._fetch_jira(open_prs.mine + open_prs.review_requests)
        stale_days = self._config.alerts.stale_days
        tracked: list[TrackedPr] = []
        for pr in open_prs.mine:
            view = analyze_my_pr(pr, open_prs.login, now, stale_days, self._jira_for(pr, jira_by_key))
            tracked.append(TrackedPr(view=view, pr=pr))
        for pr in open_prs.review_requests:
            view = analyze_review_request(pr, now, stale_days, self._jira_for(pr, jira_by_key))
            tracked.append(TrackedPr(view=view, pr=pr))
        return tracked

    def _issue_keys(self, pr: PullRequest) -> list[str]:
        project_keys = self._config.jira.project_keys if self._config.jira else []
        return find_issue_keys([pr.title, pr.head_ref], project_keys)

    def _jira_for(self, pr: PullRequest, jira_by_key: dict[str, JiraIssue]) -> list[JiraIssue]:
        return [jira_by_key[key] for key in self._issue_keys(pr) if key in jira_by_key]

    async def _fetch_jira(self, prs: list[PullRequest]) -> dict[str, JiraIssue]:
        keys: list[str] = []
        for pr in prs:
            for key in self._issue_keys(pr):
                if key not in keys:
                    keys.append(key)
        try:
            return await self._jira.fetch_issues(keys)
        except (SecretError, httpx.HTTPError) as error:
            # Jira is extra information, so a Jira failure must not stop the PR alerts.
            logger.warning("Jira lookup failed: %s", error)
            return {}

    def _send_alerts(self, events: list[Event], now: datetime) -> None:
        state = self._state
        state.snoozed_until = prune_snoozes(state.snoozed_until, now)
        state.last_alerted = prune_alert_times(self._views, state.last_alerted)
        if state.focus_until and state.focus_until > now:
            state.held_messages.extend(event.message for event in events)
            return
        state.focus_until = None
        if not is_work_time(now.astimezone(), self._config.alerts):
            return
        if state.held_messages:
            self._send_focus_done(now)
        for event in events:
            self._notify(_event_alert(event))
            state.last_alerted[event.pr_id] = now
        self._send_due_reminders(now)
        self._send_morning_summary(now)

    def _notify(self, alert: Alert) -> None:
        self._notifier.send(alert.title, alert.subtitle, alert.message, alert.url, alert.group)

    def _send_focus_done(self, now: datetime) -> None:
        count = len(self._state.held_messages)
        self._notify(
            Alert(
                title="🎯 Focus time is done",
                subtitle=f"{count} update(s) came in while you worked",
                message=reminder_message([view for view in self._views if needs_realert(view)]) or "Open PR Radar to see them.",
                url=self.dashboard_url,
                group="pr-radar-focus",
            )
        )
        self._state.held_messages = []
        for view in self._views:
            if needs_realert(view):
                self._state.last_alerted[view.id] = now

    def _send_due_reminders(self, now: datetime) -> None:
        due = due_reminders(
            self._views, self._state.last_alerted, self._state.snoozed_until, now, self._config.alerts.realert_minutes
        )
        if not due:
            return
        single = len(due) == 1
        self._notify(
            Alert(
                title="⏰ Still waiting on you" if single else f"⏰ {len(due)} PRs still need you",
                subtitle=f"{_short_repo(due[0].repo)}#{due[0].number}" if single else "Snooze a PR in PR Radar to stop this",
                message=reminder_message(due),
                url=due[0].url if single else self.dashboard_url,
                group="pr-radar-reminder",
            )
        )
        for view in due:
            self._state.last_alerted[view.id] = now

    def _send_morning_summary(self, now: datetime) -> None:
        local_now = now.astimezone()
        if not is_morning_summary_due(local_now, self._state.last_morning_summary, self._config.alerts):
            return
        self._notify(
            Alert(
                title="☀️ Good morning",
                subtitle="Your PRs today",
                message=morning_message(summarize(self._views)),
                url=self.dashboard_url,
                group="pr-radar-morning",
            )
        )
        self._state.last_morning_summary = local_now.date()

    def dashboard(self) -> Dashboard:
        now = self._clock()
        summary = summarize(self._views)
        return Dashboard(
            login=self._login,
            checked_at=self._checked_at,
            error=self._error,
            views=self._views,
            summary=summary,
            summary_lines=summary_lines(summary),
            events=self._state.events[:100],
            unread=sum(1 for event in self._state.events if not event.read),
            snoozed_until={pr_id: until for pr_id, until in self._state.snoozed_until.items() if is_snoozed(pr_id, self._state.snoozed_until, now)},
            focus_until=self._state.focus_until if self._state.focus_until and self._state.focus_until > now else None,
            is_work_time=is_work_time(now.astimezone(), self._config.alerts),
            poll_seconds=self._config.github.poll_seconds,
        )

    def menubar(self) -> str:
        if self._checked_at is None:
            return f"📡 …\n---\nChecking GitHub… | href={self.dashboard_url}\n"
        return menubar_text(self._views, self._state.focus_until, self._error, self.dashboard_url, self._clock())

    async def weekly_report(self) -> str:
        today = date.today()
        since = today - timedelta(days=7)
        activity = await self._github.fetch_weekly_activity(since)
        return weekly_report_markdown(activity, self._views, since, today)

    def mark_read(self, event_id: str | None) -> None:
        for event in self._state.events:
            if event_id is None or event.id == event_id:
                event.read = True
        self._store.save(self._state)

    def snooze(self, pr_id: str, minutes: int) -> None:
        self._state.snoozed_until[pr_id] = self._clock() + timedelta(minutes=minutes)
        self._store.save(self._state)

    def unsnooze(self, pr_id: str) -> None:
        self._state.snoozed_until.pop(pr_id, None)
        self._store.save(self._state)

    def start_focus(self, minutes: int) -> None:
        self._state.focus_until = self._clock() + timedelta(minutes=minutes)
        self._store.save(self._state)

    async def end_focus(self) -> None:
        self._state.focus_until = self._clock()
        self._store.save(self._state)
        await self.check()

    def send_test_alert(self) -> None:
        self._notify(
            Alert(
                title="🔔 PR Radar test",
                subtitle="This alert should stay on screen",
                message="If it goes away by itself, set terminal-notifier to 'Alerts' in System Settings > Notifications.",
                url=self.dashboard_url,
                group="pr-radar-test",
            )
        )

import asyncio
from datetime import time, timedelta

from builders import ME, NOW, comment, pull_request, thread

from pr_radar.config import AlertConfig, Config
from pr_radar.github import OpenPrs, PrFingerprints, fingerprints_of
from pr_radar.models import WeeklyActivity
from pr_radar.radar import Radar
from pr_radar.store import StateStore
from pr_radar.sync import RateLimit


RATE = RateLimit(limit=5000, remaining=4000, reset_at=NOW, cost=1)


class FakeGitHub:
    def __init__(self) -> None:
        self.mine = [pull_request()]
        self.full_checks = 0
        self.light_checks = 0

    async def fetch_open_prs(self) -> OpenPrs:
        self.full_checks += 1
        return OpenPrs(login=ME, mine=self.mine, review_requests=[], rate_limit=RATE)

    async def fetch_fingerprints(self) -> PrFingerprints:
        self.light_checks += 1
        open_prs = OpenPrs(login=ME, mine=self.mine, review_requests=[], rate_limit=RATE)
        return PrFingerprints(by_pr_id=fingerprints_of(open_prs), rate_limit=RATE)

    async def fetch_weekly_activity(self, since):
        return WeeklyActivity(merged=[], opened=[], reviewed=[])


class FakeJira:
    async def fetch_issues(self, keys):
        return {}


class FakeNotifier:
    def __init__(self) -> None:
        self.titles: list[str] = []

    def send(self, title, subtitle, message, url, group) -> None:
        self.titles.append(title)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):
        return self.now


def build(tmp_path):
    always_working = AlertConfig(work_days=list(range(7)), work_start=time(0), work_end=time(23, 59), morning_summary_at=time(23, 59))
    github, notifier, clock = FakeGitHub(), FakeNotifier(), Clock()
    radar = Radar(Config(alerts=always_working), github, FakeJira(), notifier, StateStore(tmp_path / "state.json"), clock)
    return radar, github, notifier, clock


def add_comment_from_sam(github):
    github.mine = [pull_request(threads=[thread("T1", [comment("C1", "sam", 0)])])]


def test_new_comment_sends_one_alert_and_no_duplicate_reminder(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.check())
    assert notifier.titles == []
    add_comment_from_sam(github)
    clock.now += timedelta(minutes=2)
    asyncio.run(radar.check())
    assert notifier.titles == ["💬 New comment"]
    clock.now += timedelta(minutes=31)
    asyncio.run(radar.check())
    assert notifier.titles == ["💬 New comment", "⏰ Still waiting on you"]


def test_focus_mode_holds_alerts_then_sends_one_summary(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.check())
    radar.start_focus(25)
    add_comment_from_sam(github)
    clock.now += timedelta(minutes=2)
    asyncio.run(radar.check())
    assert notifier.titles == []
    clock.now += timedelta(minutes=25)
    asyncio.run(radar.check())
    assert notifier.titles == ["🎯 Focus time is done"]


def test_state_survives_a_restart(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.check())
    restarted = Radar(radar._config, github, FakeJira(), notifier, StateStore(tmp_path / "state.json"), clock)
    add_comment_from_sam(github)
    asyncio.run(restarted.check())
    assert notifier.titles == ["💬 New comment"]


def test_menubar_says_checking_before_the_first_check(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    assert radar.menubar().splitlines()[0] == "📡 …"
    asyncio.run(radar.check())
    assert radar.menubar().splitlines()[0] == "✅"


def test_quick_check_without_change_does_no_full_check(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.tick())
    clock.now += timedelta(seconds=10)
    asyncio.run(radar.tick())
    assert (github.full_checks, github.light_checks) == (1, 1)


def test_quick_check_that_sees_a_change_runs_a_full_check(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.tick())
    github.mine = [pull_request(updated_minutes_ago=0, threads=[thread("T1", [comment("C1", "sam", 0)])])]
    clock.now += timedelta(seconds=10)
    asyncio.run(radar.tick())
    assert (github.full_checks, github.light_checks) == (2, 1)
    assert notifier.titles == ["💬 New comment"]


def test_safety_full_check_runs_after_the_set_minutes(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    asyncio.run(radar.tick())
    clock.now += timedelta(minutes=5)
    asyncio.run(radar.tick())
    assert github.full_checks == 2


def test_new_speed_is_saved_and_survives_a_restart(tmp_path):
    radar, github, notifier, clock = build(tmp_path)
    radar.update_sync(light_check_seconds=30, full_check_minutes=None)
    restarted = Radar(radar._config, github, FakeJira(), notifier, StateStore(tmp_path / "state.json"), clock)
    assert (restarted.sync_settings.light_check_seconds, restarted.sync_settings.full_check_minutes) == (30, 5)

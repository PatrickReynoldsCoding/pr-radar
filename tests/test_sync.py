from datetime import datetime, timedelta, timezone

from pr_radar.sync import (
    RateBudget,
    RateLimit,
    SyncSettings,
    effective_light_seconds,
    estimate_points_per_hour,
    has_changed,
    is_full_check_due,
)

NOW = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
FAST = SyncSettings(light_check_seconds=10, full_check_minutes=5)


def rate(remaining):
    return RateLimit(limit=5000, remaining=remaining, reset_at=NOW, cost=1)


def test_speed_is_kept_while_points_are_plenty():
    assert effective_light_seconds(FAST, rate(4000)) == 10
    assert effective_light_seconds(FAST, None) == 10


def test_speed_slows_down_when_points_are_low():
    assert effective_light_seconds(FAST, rate(1000)) == 60
    assert effective_light_seconds(FAST, rate(400)) == 120


def test_full_check_is_due_first_time_and_after_the_set_minutes():
    assert is_full_check_due(None, NOW, FAST, None)
    assert not is_full_check_due(NOW - timedelta(minutes=4), NOW, FAST, rate(4000))
    assert is_full_check_due(NOW - timedelta(minutes=5), NOW, FAST, rate(4000))


def test_safety_full_check_stops_when_points_are_very_low():
    assert not is_full_check_due(NOW - timedelta(minutes=30), NOW, FAST, rate(400))


def test_change_detection():
    assert has_changed(None, {})
    assert has_changed({"A": "1"}, {"A": "2"})
    assert has_changed({"A": "1"}, {"A": "1", "B": "1"})
    assert not has_changed({"A": "1"}, {"A": "1"})


def test_estimate_for_ten_seconds_and_five_minutes():
    assert estimate_points_per_hour(FAST, RateBudget(light_cost=1, full_cost=104)) == 360 + 1248

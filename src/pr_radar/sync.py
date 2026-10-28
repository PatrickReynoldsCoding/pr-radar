from datetime import datetime, timedelta

from pydantic import BaseModel, Field

# Below these shares of the hourly GitHub budget, PR Radar slows itself down.
_LOW_POINTS_SHARE = 0.25
_VERY_LOW_POINTS_SHARE = 0.10
_LOW_POINTS_LIGHT_SECONDS = 60
_VERY_LOW_POINTS_LIGHT_SECONDS = 120

MENUBAR_SPEED_CHOICES = [10, 30, 60, 120]


class SyncSettings(BaseModel):
    light_check_seconds: int = Field(ge=5, le=3600)
    full_check_minutes: int = Field(ge=1, le=120)


class RateLimit(BaseModel):
    limit: int
    remaining: int
    reset_at: datetime
    cost: int


class RateBudget(BaseModel):
    """What the last checks cost, used to estimate the hourly use of a setting."""

    light_cost: int = 1
    full_cost: int = 104


def _remaining_share(rate: RateLimit | None) -> float:
    if rate is None or rate.limit == 0:
        return 1.0
    return rate.remaining / rate.limit


def effective_light_seconds(settings: SyncSettings, rate: RateLimit | None) -> int:
    share = _remaining_share(rate)
    if share < _VERY_LOW_POINTS_SHARE:
        return max(settings.light_check_seconds, _VERY_LOW_POINTS_LIGHT_SECONDS)
    if share < _LOW_POINTS_SHARE:
        return max(settings.light_check_seconds, _LOW_POINTS_LIGHT_SECONDS)
    return settings.light_check_seconds


def is_full_check_due(last_full_at: datetime | None, now: datetime, settings: SyncSettings, rate: RateLimit | None) -> bool:
    """A safety full check catches changes the light check cannot see, such as a new merge conflict."""
    if last_full_at is None:
        return True
    if _remaining_share(rate) < _VERY_LOW_POINTS_SHARE:
        return False
    return now - last_full_at >= timedelta(minutes=settings.full_check_minutes)


def has_changed(previous: dict[str, str] | None, current: dict[str, str]) -> bool:
    return previous != current


def estimate_points_per_hour(settings: SyncSettings, budget: RateBudget) -> int:
    light_per_hour = 3600 / settings.light_check_seconds * budget.light_cost
    full_per_hour = 60 / settings.full_check_minutes * budget.full_cost
    return round(light_per_hour + full_per_hour)

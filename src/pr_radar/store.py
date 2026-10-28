from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from pr_radar.events import Event, PrSnapshot

_MAX_EVENTS = 300


class AppState(BaseModel):
    # None means GitHub has never been checked, so the next check only records a baseline.
    snapshots: dict[str, PrSnapshot] | None = None
    events: list[Event] = []
    last_alerted: dict[str, datetime] = {}
    snoozed_until: dict[str, datetime] = {}
    focus_until: datetime | None = None
    held_messages: list[str] = []
    last_morning_summary: date | None = None


def keep_latest_events(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda event: event.created_at, reverse=True)[:_MAX_EVENTS]


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AppState:
        if not self._path.exists():
            return AppState()
        return AppState.model_validate_json(self._path.read_text())

    def save(self, state: AppState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(state.model_dump_json(indent=2))
        temporary.replace(self._path)

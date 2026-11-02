from datetime import timedelta

from pydantic import BaseModel, Field

from pr_radar.analysis import IssueKind


def _days(default: int) -> int:
    return Field(default=default, ge=1, le=30)


class ReminderSettings(BaseModel):
    """How many days pass before PR Radar reminds you again, for each kind of problem."""

    review_requested_days: int = _days(2)
    changes_requested_days: int = _days(1)
    unreplied_comments_days: int = _days(1)
    ci_failed_days: int = _days(2)
    merge_conflict_days: int = _days(2)
    ready_to_merge_days: int = _days(1)
    draft_days: int = _days(2)
    # A PR with no activity for this many days. It also decides when a PR counts as quiet.
    quiet_days: int = _days(2)


_FIELD_FOR_ISSUE: dict[IssueKind, str] = {
    IssueKind.REVIEW_REQUESTED: "review_requested_days",
    IssueKind.CHANGES_REQUESTED: "changes_requested_days",
    IssueKind.UNREPLIED_COMMENTS: "unreplied_comments_days",
    IssueKind.CI_FAILED: "ci_failed_days",
    IssueKind.MERGE_CONFLICT: "merge_conflict_days",
    IssueKind.READY_TO_MERGE: "ready_to_merge_days",
    IssueKind.DRAFT: "draft_days",
}


def reminder_wait(settings: ReminderSettings, kind: IssueKind) -> timedelta:
    return timedelta(days=getattr(settings, _FIELD_FOR_ISSUE[kind]))

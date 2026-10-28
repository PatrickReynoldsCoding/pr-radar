from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class Mergeable(StrEnum):
    MERGEABLE = "MERGEABLE"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class CheckState(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ERROR = "ERROR"
    PENDING = "PENDING"
    EXPECTED = "EXPECTED"


class Comment(BaseModel):
    id: str
    author: str
    body: str
    created_at: datetime
    url: str


class Review(BaseModel):
    id: str
    author: str
    state: str
    body: str
    submitted_at: datetime | None
    url: str


class ReviewThread(BaseModel):
    id: str
    is_resolved: bool
    comments: list[Comment]


class PullRequest(BaseModel):
    id: str
    number: int
    title: str
    url: str
    repo: str
    author: str
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    head_ref: str
    review_decision: ReviewDecision | None
    mergeable: Mergeable
    check_state: CheckState | None
    comments: list[Comment]
    reviews: list[Review]
    threads: list[ReviewThread]


class ShippedPr(BaseModel):
    number: int
    title: str
    url: str
    repo: str
    at: datetime


class WeeklyActivity(BaseModel):
    merged: list[ShippedPr]
    opened: list[ShippedPr]
    reviewed: list[ShippedPr]


class JiraIssue(BaseModel):
    key: str
    status: str
    summary: str
    url: str

from datetime import date, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from pr_radar.config import GitHubConfig
from pr_radar.models import (
    CheckState,
    Comment,
    Mergeable,
    PullRequest,
    Review,
    ReviewDecision,
    ReviewThread,
    ShippedPr,
    WeeklyActivity,
)
from pr_radar.secrets import read_secret
from pr_radar.sync import RateLimit

_GHOST_LOGIN = "ghost"

_PR_FIELDS = """
  id number title url isDraft createdAt updatedAt headRefName
  repository { nameWithOwner }
  author { login __typename }
  reviewDecision mergeable
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  comments(last: 30) { nodes { id author { login __typename } body createdAt url } }
  reviews(last: 30) { nodes { id author { login __typename } state body submittedAt url } }
  reviewThreads(first: 50) { nodes { id isResolved
    comments(last: 10) { nodes { id author { login __typename } body createdAt url } } } }
"""

_RATE_LIMIT_FIELDS = "rateLimit { limit remaining resetAt cost }"

_OPEN_PRS_QUERY = f"""
query($mine: String!, $reviews: String!) {{
  viewer {{ login }}
  {_RATE_LIMIT_FIELDS}
  mine: search(query: $mine, type: ISSUE, first: 50) {{ nodes {{ ... on PullRequest {{ {_PR_FIELDS} }} }} }}
  reviews: search(query: $reviews, type: ISSUE, first: 50) {{ nodes {{ ... on PullRequest {{ {_PR_FIELDS} }} }} }}
}}
"""

_FINGERPRINT_FIELDS = "id updatedAt commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"

_FINGERPRINTS_QUERY = f"""
query($mine: String!, $reviews: String!) {{
  {_RATE_LIMIT_FIELDS}
  mine: search(query: $mine, type: ISSUE, first: 50) {{ nodes {{ ... on PullRequest {{ {_FINGERPRINT_FIELDS} }} }} }}
  reviews: search(query: $reviews, type: ISSUE, first: 50) {{ nodes {{ ... on PullRequest {{ {_FINGERPRINT_FIELDS} }} }} }}
}}
"""

_SHIPPED_FIELDS = "number title url createdAt updatedAt mergedAt repository { nameWithOwner }"

_WEEKLY_QUERY = f"""
query($merged: String!, $opened: String!, $reviewed: String!) {{
  merged: search(query: $merged, type: ISSUE, first: 100) {{ nodes {{ ... on PullRequest {{ {_SHIPPED_FIELDS} }} }} }}
  opened: search(query: $opened, type: ISSUE, first: 100) {{ nodes {{ ... on PullRequest {{ {_SHIPPED_FIELDS} }} }} }}
  reviewed: search(query: $reviewed, type: ISSUE, first: 100) {{ nodes {{ ... on PullRequest {{ {_SHIPPED_FIELDS} }} }} }}
}}
"""


class OpenPrs(BaseModel):
    login: str
    mine: list[PullRequest]
    review_requests: list[PullRequest]
    rate_limit: RateLimit


class PrFingerprints(BaseModel):
    """A cheap summary of each open PR. When it changes, a full check is needed."""

    by_pr_id: dict[str, str]
    rate_limit: RateLimit


def fingerprint(updated_at: datetime, check_state: CheckState | None) -> str:
    # updatedAt moves on comments, reviews and pushes. Check results do not move it, so add them.
    return f"{updated_at.isoformat()}|{check_state or ''}"


def fingerprints_of(open_prs: OpenPrs) -> dict[str, str]:
    return {pr.id: fingerprint(pr.updated_at, pr.check_state) for pr in open_prs.mine + open_prs.review_requests}


class GitHubError(Exception):
    pass


class GitHubClient(Protocol):
    async def fetch_open_prs(self) -> OpenPrs: ...

    async def fetch_fingerprints(self) -> PrFingerprints: ...

    async def fetch_weekly_activity(self, since: date) -> WeeklyActivity: ...


def build_github_client(config: GitHubConfig) -> GitHubClient:
    return _GraphQlGitHubClient(config)


class _Gql(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Actor(_Gql):
    login: str
    typename: str = Field(alias="__typename")


class _Repo(_Gql):
    name_with_owner: str


class _GqlComment(_Gql):
    id: str
    author: _Actor | None
    body: str
    created_at: datetime
    url: str


class _GqlReview(_Gql):
    id: str
    author: _Actor | None
    state: str
    body: str
    submitted_at: datetime | None
    url: str


class _CommentNodes(_Gql):
    nodes: list[_GqlComment]


class _GqlThread(_Gql):
    id: str
    is_resolved: bool
    comments: _CommentNodes


class _Rollup(_Gql):
    state: CheckState


class _Commit(_Gql):
    status_check_rollup: _Rollup | None


class _CommitNode(_Gql):
    commit: _Commit


class _CommitNodes(_Gql):
    nodes: list[_CommitNode]


class _ReviewNodes(_Gql):
    nodes: list[_GqlReview]


class _ThreadNodes(_Gql):
    nodes: list[_GqlThread]


class _GqlPullRequest(_Gql):
    id: str
    number: int
    title: str
    url: str
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    head_ref_name: str
    repository: _Repo
    author: _Actor | None
    review_decision: ReviewDecision | None
    mergeable: Mergeable
    commits: _CommitNodes
    comments: _CommentNodes
    reviews: _ReviewNodes
    review_threads: _ThreadNodes


class _PrNodes(_Gql):
    nodes: list[_GqlPullRequest]


class _Viewer(_Gql):
    login: str


class _GqlRateLimit(_Gql):
    limit: int
    remaining: int
    reset_at: datetime
    cost: int

    def to_rate_limit(self) -> RateLimit:
        return RateLimit(limit=self.limit, remaining=self.remaining, reset_at=self.reset_at, cost=self.cost)


class _GqlFingerprintPr(_Gql):
    id: str
    updated_at: datetime
    commits: _CommitNodes


class _FingerprintNodes(_Gql):
    nodes: list[_GqlFingerprintPr]


class _FingerprintsData(_Gql):
    rate_limit: _GqlRateLimit
    mine: _FingerprintNodes
    reviews: _FingerprintNodes


class _OpenPrsData(_Gql):
    viewer: _Viewer
    rate_limit: _GqlRateLimit
    mine: _PrNodes
    reviews: _PrNodes


class _GqlShipped(_Gql):
    number: int
    title: str
    url: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    repository: _Repo


class _ShippedNodes(_Gql):
    nodes: list[_GqlShipped]


class _WeeklyData(_Gql):
    merged: _ShippedNodes
    opened: _ShippedNodes
    reviewed: _ShippedNodes


def _login(actor: _Actor | None) -> str:
    if actor is None:
        return _GHOST_LOGIN
    # The GraphQL API drops the "[bot]" ending from bot logins, so add it back to keep one bot rule everywhere.
    return f"{actor.login}[bot]" if actor.typename == "Bot" else actor.login


def _to_comment(raw: _GqlComment) -> Comment:
    return Comment(id=raw.id, author=_login(raw.author), body=raw.body, created_at=raw.created_at, url=raw.url)


def _to_review(raw: _GqlReview) -> Review:
    return Review(
        id=raw.id,
        author=_login(raw.author),
        state=raw.state,
        body=raw.body,
        submitted_at=raw.submitted_at,
        url=raw.url,
    )


def _to_thread(raw: _GqlThread) -> ReviewThread:
    return ReviewThread(
        id=raw.id,
        is_resolved=raw.is_resolved,
        comments=[_to_comment(comment) for comment in raw.comments.nodes],
    )


def _check_state(commits: _CommitNodes) -> CheckState | None:
    rollup = commits.nodes[0].commit.status_check_rollup if commits.nodes else None
    return rollup.state if rollup else None


def _to_pull_request(raw: _GqlPullRequest) -> PullRequest:
    return PullRequest(
        id=raw.id,
        number=raw.number,
        title=raw.title,
        url=raw.url,
        repo=raw.repository.name_with_owner,
        author=_login(raw.author),
        is_draft=raw.is_draft,
        created_at=raw.created_at,
        updated_at=raw.updated_at,
        head_ref=raw.head_ref_name,
        review_decision=raw.review_decision,
        mergeable=raw.mergeable,
        check_state=_check_state(raw.commits),
        comments=[_to_comment(comment) for comment in raw.comments.nodes],
        reviews=[_to_review(review) for review in raw.reviews.nodes],
        threads=[_to_thread(thread) for thread in raw.review_threads.nodes],
    )


def _to_shipped(raw: _GqlShipped, at: datetime) -> ShippedPr:
    return ShippedPr(number=raw.number, title=raw.title, url=raw.url, repo=raw.repository.name_with_owner, at=at)


def search_query(base: str, orgs: list[str]) -> str:
    org_filters = " ".join(f"org:{org}" for org in orgs)
    return f"{base} archived:false {org_filters}".strip()


def _non_empty_nodes(nodes: list[dict]) -> list[dict]:
    # Search results that are not PRs come back as empty objects.
    return [node for node in nodes if node]


def _clean_search_results(data: dict, keys: list[str]) -> dict:
    cleaned = dict(data)
    for key in keys:
        cleaned[key] = {"nodes": _non_empty_nodes(data[key]["nodes"])}
    return cleaned


class _GraphQlGitHubClient:
    def __init__(self, config: GitHubConfig) -> None:
        self._config = config

    def _open_pr_searches(self) -> dict[str, str]:
        review_filter = "review-requested:@me" if self._config.include_team_review_requests else "user-review-requested:@me"
        return {
            "mine": search_query("is:pr is:open author:@me", self._config.orgs),
            "reviews": search_query(f"is:pr is:open {review_filter}", self._config.orgs),
        }

    async def fetch_fingerprints(self) -> PrFingerprints:
        data = await self._query(_FINGERPRINTS_QUERY, self._open_pr_searches())
        parsed = _FingerprintsData.model_validate(_clean_search_results(data, ["mine", "reviews"]))
        by_pr_id: dict[str, str] = {}
        for raw in parsed.mine.nodes + parsed.reviews.nodes:
            by_pr_id[raw.id] = fingerprint(raw.updated_at, _check_state(raw.commits))
        return PrFingerprints(by_pr_id=by_pr_id, rate_limit=parsed.rate_limit.to_rate_limit())

    async def fetch_open_prs(self) -> OpenPrs:
        data = await self._query(_OPEN_PRS_QUERY, self._open_pr_searches())
        parsed = _OpenPrsData.model_validate(_clean_search_results(data, ["mine", "reviews"]))
        return OpenPrs(
            login=parsed.viewer.login,
            mine=[_to_pull_request(raw) for raw in parsed.mine.nodes],
            review_requests=[_to_pull_request(raw) for raw in parsed.reviews.nodes],
            rate_limit=parsed.rate_limit.to_rate_limit(),
        )

    async def fetch_weekly_activity(self, since: date) -> WeeklyActivity:
        since_text = since.isoformat()
        variables = {
            "merged": search_query(f"is:pr author:@me is:merged merged:>={since_text}", self._config.orgs),
            "opened": search_query(f"is:pr author:@me created:>={since_text}", self._config.orgs),
            "reviewed": search_query(f"is:pr reviewed-by:@me -author:@me updated:>={since_text}", self._config.orgs),
        }
        data = await self._query(_WEEKLY_QUERY, variables)
        parsed = _WeeklyData.model_validate(_clean_search_results(data, ["merged", "opened", "reviewed"]))
        return WeeklyActivity(
            merged=[_to_shipped(raw, raw.merged_at or raw.updated_at) for raw in parsed.merged.nodes],
            opened=[_to_shipped(raw, raw.created_at) for raw in parsed.opened.nodes],
            reviewed=[_to_shipped(raw, raw.updated_at) for raw in parsed.reviewed.nodes],
        )

    async def _query(self, query: str, variables: dict[str, str]) -> dict:
        token = read_secret(self._config.token_command)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self._config.graphql_url,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise GitHubError(f"GitHub returned HTTP {response.status_code}")
        body = response.json()
        if body.get("errors"):
            raise GitHubError("; ".join(error["message"] for error in body["errors"]))
        return body["data"]

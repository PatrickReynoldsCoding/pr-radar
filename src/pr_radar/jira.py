import re
from typing import Protocol

import httpx
from pydantic import BaseModel

from pr_radar.config import JiraConfig
from pr_radar.models import JiraIssue
from pr_radar.secrets import read_secret

_ISSUE_KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def find_issue_keys(texts: list[str], project_keys: list[str]) -> list[str]:
    allowed_projects = set(project_keys)
    found: list[str] = []
    for text in texts:
        for key in _ISSUE_KEY.findall(text.upper()):
            project = key.split("-")[0]
            is_allowed = not allowed_projects or project in allowed_projects
            if is_allowed and key not in found:
                found.append(key)
    return found


class _JiraStatus(BaseModel):
    name: str


class _JiraFields(BaseModel):
    status: _JiraStatus
    summary: str


class _JiraIssueResponse(BaseModel):
    fields: _JiraFields


class JiraClient(Protocol):
    async def fetch_issues(self, keys: list[str]) -> dict[str, JiraIssue]: ...


def build_jira_client(config: JiraConfig | None) -> JiraClient:
    return _RestJiraClient(config) if config else _NoJiraClient()


class _NoJiraClient:
    async def fetch_issues(self, keys: list[str]) -> dict[str, JiraIssue]:
        return {}


class _RestJiraClient:
    def __init__(self, config: JiraConfig) -> None:
        self._config = config

    async def fetch_issues(self, keys: list[str]) -> dict[str, JiraIssue]:
        if not keys:
            return {}
        base_url = self._config.base_url.rstrip("/")
        token = read_secret(self._config.token_command)
        issues: dict[str, JiraIssue] = {}
        async with httpx.AsyncClient(timeout=20, auth=(self._config.email, token)) as client:
            for key in keys:
                response = await client.get(f"{base_url}/rest/api/3/issue/{key}", params={"fields": "status,summary"})
                # Keys that look like Jira keys but are not (for example "UTF-8") give 404, so skip them.
                if response.status_code != 200:
                    continue
                fields = _JiraIssueResponse.model_validate(response.json()).fields
                issues[key] = JiraIssue(
                    key=key,
                    status=fields.status.name,
                    summary=fields.summary,
                    url=f"{base_url}/browse/{key}",
                )
        return issues

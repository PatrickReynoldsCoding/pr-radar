import tomllib
from datetime import time
from pathlib import Path

from pydantic import BaseModel

CONFIG_PATH = Path.home() / ".config" / "pr-radar" / "config.toml"
DATA_DIR = Path.home() / ".local" / "share" / "pr-radar"


class GitHubConfig(BaseModel):
    orgs: list[str] = []
    token_command: str = "gh auth token"
    graphql_url: str = "https://api.github.com/graphql"
    light_check_seconds: int = 10
    full_check_minutes: int = 5
    include_team_review_requests: bool = False


class AlertConfig(BaseModel):
    realert_minutes: int = 30
    stale_days: int = 3
    work_days: list[int] = [0, 1, 2, 3, 4]
    work_start: time = time(9, 0)
    work_end: time = time(18, 0)
    morning_summary_at: time = time(9, 15)
    sound: str = "default"


class JiraConfig(BaseModel):
    base_url: str
    email: str
    token_command: str
    project_keys: list[str] = []


class PrivacyConfig(BaseModel):
    forbidden_words: list[str] = []


class Config(BaseModel):
    port: int = 4747
    github: GitHubConfig = GitHubConfig()
    alerts: AlertConfig = AlertConfig()
    jira: JiraConfig | None = None
    privacy: PrivacyConfig = PrivacyConfig()


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    return Config.model_validate(tomllib.loads(path.read_text()))

import logging

import uvicorn

from pr_radar.config import DATA_DIR, load_config
from pr_radar.github import build_github_client
from pr_radar.jira import build_jira_client
from pr_radar.notifier import build_notifier
from pr_radar.radar import Radar
from pr_radar.server import build_app
from pr_radar.store import StateStore


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    radar = Radar(
        config=config,
        github=build_github_client(config.github),
        jira=build_jira_client(config.jira),
        notifier=build_notifier(config.alerts.sound),
        store=StateStore(DATA_DIR / "state.json"),
    )
    # Bind to localhost only: the page shows private PR data and has no login.
    uvicorn.run(build_app(radar), host="127.0.0.1", port=config.port, log_level="warning")


if __name__ == "__main__":
    main()

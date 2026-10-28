"""Fails if a word from your private list appears in the repo, so it is never committed.

The list lives in your own config file (outside the repo): [privacy] forbidden_words = ["..."].
"""

import subprocess
from pathlib import Path

from pr_radar.config import load_config

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [_REPO_ROOT / name for name in listed.stdout.splitlines() if (_REPO_ROOT / name).is_file()]


def test_no_private_words_in_repo():
    forbidden = [word.lower() for word in load_config().privacy.forbidden_words]
    found: list[str] = []
    for path in _repo_files():
        text = path.read_text(errors="ignore").lower()
        for word in forbidden:
            if word in text:
                found.append(f"{path.relative_to(_REPO_ROOT)}: '{word}'")
    assert not found, "Private words found:\n" + "\n".join(found)

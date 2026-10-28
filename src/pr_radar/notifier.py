import shutil
import subprocess
import threading
from typing import Protocol

_FALLBACK_PATHS = ["/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier"]


class Notifier(Protocol):
    def send(self, title: str, subtitle: str, message: str, url: str, group: str) -> None: ...


def build_notifier(sound: str) -> Notifier:
    return _TerminalNotifier(_find_terminal_notifier(), sound)


def _find_terminal_notifier() -> str:
    found = shutil.which("terminal-notifier")
    if found:
        return found
    for path in _FALLBACK_PATHS:
        if shutil.which(path):
            return path
    raise FileNotFoundError("terminal-notifier is not installed. Run: brew install terminal-notifier")


class _TerminalNotifier:
    def __init__(self, binary: str, sound: str) -> None:
        self._binary = binary
        self._sound = sound

    def send(self, title: str, subtitle: str, message: str, url: str, group: str) -> None:
        command = [
            self._binary,
            "-title", title,
            "-subtitle", subtitle,
            # A leading "[" or "-" is read as an option, so escape it.
            "-message", "\\" + message if message[:1] in {"[", "-"} else message,
            "-open", url,
            "-group", group,
            "-sound", self._sound,
        ]
        # Run in the background so a slow notification never blocks the GitHub check.
        threading.Thread(target=subprocess.run, args=(command,), kwargs={"capture_output": True}, daemon=True).start()

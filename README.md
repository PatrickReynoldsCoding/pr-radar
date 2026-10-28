# PR Radar

PR Radar watches your open GitHub pull requests. It tells you when someone waits on you.
It is made for people who forget things easily (for example, people with ADHD).

It runs on your Mac. It shows a web page, sends Mac alerts that stay on screen, and shows an icon in the menu bar.

## What it does

- **Do this next.** The top of the page shows the one most important thing to do.
- **One next action per PR.** For example "Reply to 2 comments from sam" or "Fix the failing checks".
- **Alerts when something changes:**
  - 💬 New comment on your PR (bots are ignored)
  - ✏️ Changes requested
  - ❌ Checks failed
  - ⚔️ Merge conflict
  - 🚀 Approved and ready to merge
  - 👀 Someone asked you to review their PR
  - 💤 Your PR has gone quiet for some days
- **Reminders.** If a PR still needs you after 30 minutes, you get another alert. Snooze a PR to stop it.
- **Focus mode.** Hold all alerts for 25, 50 or 90 minutes. You get one summary at the end.
- **Work hours.** Mac alerts only come on work days, in work hours.
- **Morning summary.** One alert each work day with what needs you today.
- **Weekly report.** "What I shipped" in Markdown (merged, reviewed, opened, still open). Copy it into your 1:1 notes.
- **Jira status** next to each PR (optional).
- **Menu bar icon** (with [SwiftBar](https://github.com/swiftbar/SwiftBar)) with a count, links to each PR and focus buttons.

## Install

You need [uv](https://docs.astral.sh/uv/), [GitHub CLI](https://cli.github.com/) (logged in with `gh auth login`) and terminal-notifier.

```bash
brew install uv gh terminal-notifier
brew install --cask swiftbar   # optional, for the menu bar icon
./scripts/install.sh
```

The install script:
1. Makes `~/.config/pr-radar/config.toml` from `config.example.toml`. Edit it to set your GitHub orgs.
2. Starts PR Radar now and at every login.
3. Adds the menu bar plugin if SwiftBar is set up.

Then open http://127.0.0.1:4747/.

### Make alerts stay on screen

macOS has two alert styles: **Banners** go away by themselves. **Alerts** stay until you close them.

1. Open **System Settings → Notifications**.
2. Find **terminal-notifier** in the list.
3. Set the style to **Alerts**.
4. On the PR Radar page, click **Send a test Mac alert** to check.

## Settings

All settings are in `~/.config/pr-radar/config.toml`. See `config.example.toml` for each setting.
After a change, restart PR Radar:

```bash
launchctl kickstart -k gui/$(id -u)/com.pr-radar.server
```

## Keep private names out of the repo

Put your employer and org names in `[privacy] forbidden_words` in your config.
The test `tests/test_no_private_words.py` fails if any of these words is in a repo file.
Run the tests before each commit:

```bash
uv run pytest
```

## Remove

```bash
./scripts/uninstall.sh
```

## Where things are

| What | Where |
|---|---|
| Your settings | `~/.config/pr-radar/config.toml` |
| Saved state (alerts, snoozes) | `~/.local/share/pr-radar/state.json` |
| Log | `~/Library/Logs/pr-radar.log` |

## Privacy and security

- The page only listens on `127.0.0.1`, so other computers cannot open it.
- It rejects requests that use another host name, and actions need a special header. This stops other websites from reading your PRs or changing your settings.
- Tokens are never saved. PR Radar runs a command (such as `gh auth token`) each time it needs one.

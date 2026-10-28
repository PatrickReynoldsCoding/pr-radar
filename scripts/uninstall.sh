#!/usr/bin/env bash
# Stops PR Radar and removes the login item, the app and the menu bar plugin. Your config and state stay.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/common.sh"

launchctl bootout "${domain}/${label}" 2>/dev/null || true
rm -f "${launch_agent_plist}"
rm -rf "${HOME}/Applications/PR Radar.app"

plugin_dir=$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)
if [[ -n "${plugin_dir}" ]]; then
    rm -f "${plugin_dir}/pr-radar.30s.sh"
fi
echo "PR Radar is removed. SwiftBar is still installed. Config: ~/.config/pr-radar. State: ~/.local/share/pr-radar."

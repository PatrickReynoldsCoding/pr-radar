#!/usr/bin/env bash
# SwiftBar plugin for PR Radar. Refreshes every 30 seconds.
set -uo pipefail

scripts_dir="$(cd "$(dirname "$(readlink -f "$0")")/../scripts" && pwd)"
source "${scripts_dir}/common.sh"

if /usr/bin/curl -s --fail --max-time 3 "$(dashboard_url)api/menubar"; then
    echo "---"
    echo "Stop PR Radar | bash=${scripts_dir}/stop.sh terminal=false refresh=true"
else
    echo "📡 off"
    echo "---"
    echo "PR Radar is stopped"
    echo "Start PR Radar | bash=${scripts_dir}/start.sh terminal=false refresh=true"
fi

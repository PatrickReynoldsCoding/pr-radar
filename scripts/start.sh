#!/usr/bin/env bash
# Starts PR Radar if it is stopped, then opens the page.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/common.sh"

if [[ ! -f "${launch_agent_plist}" ]]; then
    osascript -e 'display alert "PR Radar is not installed" message "Run scripts/install.sh first."'
    exit 1
fi
if ! launchctl print "${domain}/${label}" >/dev/null 2>&1; then
    launchctl bootstrap "${domain}" "${launch_agent_plist}"
fi
launchctl kickstart "${domain}/${label}"

url="$(dashboard_url)"
for _ in $(seq 1 30); do
    if /usr/bin/curl -s -o /dev/null --max-time 1 "${url}api/dashboard"; then
        break
    fi
    sleep 1
done
if [[ "${1:-}" != "--no-open" ]]; then
    open "${url}"
fi

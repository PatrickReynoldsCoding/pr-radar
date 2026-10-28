#!/usr/bin/env bash
# Stops PR Radar until you start it again or log in again.
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/common.sh"

launchctl bootout "${domain}/${label}" 2>/dev/null || true
echo "PR Radar is stopped. Start it again with scripts/start.sh, the PR Radar app or the menu bar."

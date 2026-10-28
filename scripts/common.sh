# Shared values for the PR Radar scripts. Source this file; do not run it.
label="com.pr-radar.server"
domain="gui/$(id -u)"
launch_agent_plist="${HOME}/Library/LaunchAgents/${label}.plist"
config_file="${HOME}/.config/pr-radar/config.toml"

configured_port() {
    local port
    port=$(sed -n 's/^port *= *\([0-9]*\).*/\1/p' "${config_file}" 2>/dev/null | head -1)
    echo "${port:-4747}"
}

dashboard_url() {
    echo "http://127.0.0.1:$(configured_port)/"
}

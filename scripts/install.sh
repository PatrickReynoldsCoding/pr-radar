#!/usr/bin/env bash
# Installs PR Radar: a login item (launchd), a "PR Radar" app to start it by hand,
# and the SwiftBar menu bar icon if SwiftBar is installed.
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
source "${repo_dir}/scripts/common.sh"
log_file="${HOME}/Library/Logs/pr-radar.log"
app_path="${HOME}/Applications/PR Radar.app"
swiftbar_app="/Applications/SwiftBar.app"

require() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing $1. Install it with: brew install $2" >&2
        exit 1
    fi
}

write_launch_agent() {
    local uv_path="$1"
    cat > "${launch_agent_plist}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${uv_path}</string>
        <string>run</string>
        <string>--project</string>
        <string>${repo_dir}</string>
        <string>pr-radar</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${log_file}</string>
    <key>StandardErrorPath</key>
    <string>${log_file}</string>
</dict>
</plist>
PLIST
}

build_app_icon() {
    local icon_dir
    icon_dir="$(mktemp -d)/PRRadar.iconset"
    mkdir -p "${icon_dir}"
    for size in 16 32 128 256 512; do
        sips -z "${size}" "${size}" "${repo_dir}/assets/icon.png" --out "${icon_dir}/icon_${size}x${size}.png" >/dev/null
        sips -z $((size * 2)) $((size * 2)) "${repo_dir}/assets/icon.png" --out "${icon_dir}/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "${icon_dir}" -o "${app_path}/Contents/Resources/applet.icns"
}

install_app() {
    mkdir -p "${HOME}/Applications"
    rm -rf "${app_path}"
    osacompile -o "${app_path}" -e "do shell script quoted form of \"${repo_dir}/scripts/start.sh\""
    build_app_icon
    # A new icon breaks the app's seal, so sign it again (ad hoc, for this Mac only).
    codesign --force --sign - "${app_path}" >/dev/null 2>&1
    touch "${app_path}"
    echo "Made ${app_path}. Open it from Spotlight, Launchpad or the Dock to start PR Radar."
}

is_swiftbar_login_item() {
    osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q "SwiftBar"
}

install_menubar_plugin() {
    local plugin_dir
    plugin_dir=$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)
    if [[ ! -d "${swiftbar_app}" || -z "${plugin_dir}" ]]; then
        echo "SwiftBar is not set up, so no menu bar icon. Install it with: brew install --cask swiftbar"
        echo "Then open SwiftBar once, choose a plugin folder, and run this script again."
        return
    fi
    ln -sf "${repo_dir}/menubar/pr-radar.30s.sh" "${plugin_dir}/pr-radar.30s.sh"
    echo "Menu bar plugin linked into ${plugin_dir}"
    if ! is_swiftbar_login_item; then
        osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"${swiftbar_app}\", hidden:false}" >/dev/null
        echo "SwiftBar now starts at login."
    fi
    open -g "${swiftbar_app}"
}

require uv uv
require terminal-notifier terminal-notifier
require gh gh

mkdir -p "$(dirname "${config_file}")" "$(dirname "${launch_agent_plist}")" "$(dirname "${log_file}")"
if [[ ! -f "${config_file}" ]]; then
    cp "${repo_dir}/config.example.toml" "${config_file}"
    echo "Made ${config_file}. Edit it to set your GitHub orgs."
fi

(cd "${repo_dir}" && uv sync --quiet)
write_launch_agent "$(command -v uv)"

# bootout fails when the job is not loaded yet, which is fine on a first install.
launchctl bootout "${domain}/${label}" 2>/dev/null || true
# bootout returns before the job is fully gone, and bootstrap fails until it is.
for _ in $(seq 1 20); do
    launchctl print "${domain}/${label}" >/dev/null 2>&1 || break
    sleep 0.5
done
launchctl bootstrap "${domain}" "${launch_agent_plist}"
install_app
install_menubar_plugin

echo "PR Radar is running. It starts again at every login."
echo "Open it: $(dashboard_url)"
echo "Logs: ${log_file}"

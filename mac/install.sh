#!/bin/sh
# Sets up the Mac side:
#   - The "Kobo Reading Stats" app (in ~/Applications, opens from Spotlight). Opening it shows the dashboard.
#   - A launchd agent that runs the app in the background every time the Kobo is plugged in.
# macOS grants access to removable drives per app, so Python runs through this app instead of
# directly; macOS asks for permission once, the first time.
# To remove: mac/uninstall.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
LABEL=io.github.alihanayd.kobo-reading-stats
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
APP="$HOME/Applications/Kobo Reading Stats.app"

# If KOBO_STATS_LANG is set (en/tr), it's baked into the app; otherwise the script follows macOS.
case "${KOBO_STATS_LANG:-}" in
    en|tr) LANG_ENV="KOBO_STATS_LANG=$KOBO_STATS_LANG " ;;
    "") LANG_ENV="" ;;
    *) echo "KOBO_STATS_LANG must be en or tr." >&2; exit 1 ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Applications" "$ROOT/data"

TMP=$(mktemp -d)
SOURCE=$TMP/app.applescript
cat > "$SOURCE" <<EOF
use AppleScript version "2.4"
use framework "Foundation"
use scripting additions

property scriptPath : "$ROOT/mac/kobo_stats.py"
property logPath : "$ROOT/data/auto.log"

on run
	set args to (current application's NSProcessInfo's processInfo()'s arguments()) as list
	set mode to ""
	if args contains "--auto" then set mode to " --auto"
	do shell script "${LANG_ENV}/usr/bin/python3 " & quoted form of scriptPath & mode & " >> " & quoted form of logPath & " 2>&1 || true"
end run
EOF
rm -rf "$APP"
osacompile -o "$APP" "$SOURCE"
rm -rf "$TMP"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-g</string>
        <string>-n</string>
        <string>-a</string>
        <string>$APP</string>
        <string>--args</string>
        <string>--auto</string>
    </array>
    <!-- Runs whenever any disk is mounted; the script exits right away if it isn't the Kobo. -->
    <key>StartOnMount</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$ROOT/data/auto.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/data/auto.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed:"
echo "  app:           $APP"
echo "  launchd agent: $PLIST"

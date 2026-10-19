#!/bin/sh
# Removes the Mac side. The collected data (data/) is kept.
LABEL=io.github.alihanayd.kobo-reading-stats
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Kobo Reading Stats.app"
echo "Mac side removed. Your data is still in $(cd "$(dirname "$0")/.." && pwd)/data."

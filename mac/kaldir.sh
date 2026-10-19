#!/bin/sh
# Mac tarafını kaldırır. Toplanan veriler (veri/) silinmez.
ETIKET=com.gurmehub.kobo-istatistik
launchctl bootout "gui/$(id -u)/$ETIKET" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$ETIKET.plist"
rm -rf "$HOME/Applications/Kobo İstatistik.app"
echo "Mac tarafı kaldırıldı. Veriler $(cd "$(dirname "$0")/.." && pwd)/veri altında duruyor."

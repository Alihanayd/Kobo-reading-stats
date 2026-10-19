#!/bin/sh
# Mac tarafını kurar:
#   - "Kobo İstatistik" uygulaması (~/Applications, Spotlight'tan açılır). Açınca paneli gösterir.
#   - Kobo her takıldığında bu uygulamayı arka planda çalıştıran launchd görevi.
# macOS çıkarılabilir disklere erişimi uygulama bazında izinle verdiği için Python'u doğrudan
# değil, bu uygulama üzerinden çalıştırıyoruz; ilk seferde macOS bir kez izin ister.
# Kaldırmak için: mac/kaldir.sh
set -eu

KOK=$(cd "$(dirname "$0")/.." && pwd)
ETIKET=com.gurmehub.kobo-istatistik
PLIST=$HOME/Library/LaunchAgents/$ETIKET.plist
UYGULAMA="$HOME/Applications/Kobo İstatistik.app"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Applications" "$KOK/veri"

GECICI=$(mktemp -d)
KAYNAK=$GECICI/uygulama.applescript
cat > "$KAYNAK" <<EOF
use AppleScript version "2.4"
use framework "Foundation"
use scripting additions

property betik : "$KOK/mac/kobo_istatistik.py"
property gunluk : "$KOK/veri/otomatik.log"

on run
	set argumanlar to (current application's NSProcessInfo's processInfo()'s arguments()) as list
	set secenek to ""
	if argumanlar contains "--otomatik" then set secenek to " --otomatik"
	do shell script "/usr/bin/python3 " & quoted form of betik & secenek & " >> " & quoted form of gunluk & " 2>&1 || true"
end run
EOF
rm -rf "$UYGULAMA"
osacompile -o "$UYGULAMA" "$KAYNAK"
rm -rf "$GECICI"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$ETIKET</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-g</string>
        <string>-n</string>
        <string>-a</string>
        <string>$UYGULAMA</string>
        <string>--args</string>
        <string>--otomatik</string>
    </array>
    <!-- Herhangi bir disk bağlandığında çalışır; Kobo değilse betik hemen çıkar. -->
    <key>StartOnMount</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$KOK/veri/otomatik.log</string>
    <key>StandardErrorPath</key>
    <string>$KOK/veri/otomatik.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$ETIKET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Kuruldu:"
echo "  uygulama:       $UYGULAMA"
echo "  launchd görevi: $PLIST"

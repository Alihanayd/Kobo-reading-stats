#!/bin/sh
# Reads the total reading time Kobo keeps for each book once a minute and appends the
# rows that changed to /mnt/onboard/.adds/reading-stats/history.tsv.
#
# history.tsv columns (tab-separated):
#   logged at (Unix time, UTC) | ContentID | TimeSpentReading (s) | ___PercentRead |
#   ReadStatus (0 unread, 1 reading, 2 finished) | DateLastRead | Title
#
# To uninstall: connect the Kobo to a computer, create an empty file named
# .adds/reading-stats/UNINSTALL and eject the device. The logger removes itself within a minute.

VERSION=2
DIR=/usr/local/reading-stats
SQLITE=$DIR/sqlite3
DB=/mnt/onboard/.kobo/KoboReader.sqlite
OUT=/mnt/onboard/.adds/reading-stats
SNAPSHOT=/tmp/reading-stats.snapshot
INTERVAL=60
TAB=$(printf '\t')

# Version 1 was installed under the name "okumakaydi". The first few rounds after start
# stop and remove that copy, and its records are moved into history.tsv.
LEGACY_DIR=/usr/local/okumakaydi
LEGACY_RULE=/etc/udev/rules.d/98-okumakaydi.rules
LEGACY_OUT=/mnt/onboard/.adds/okumakaydi
LEGACY_ROUNDS=3

cd /

onboard_mounted() {
    # While USB is connected, /mnt/onboard is handed to the computer; don't write to it then.
    grep -q ' /mnt/onboard ' /proc/mounts
}

log() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >> "$OUT/logger.log"
}

uninstall() {
    log "UNINSTALL file found, removing the logger"
    rm -f /etc/udev/rules.d/98-reading-stats.rules
    rm -rf "$DIR" /tmp/reading-stats.lock "$SNAPSHOT"
    mv "$OUT/UNINSTALL" "$OUT/UNINSTALLED" 2>/dev/null
    exit 0
}

remove_legacy_logger() {
    # The bracket keeps grep from matching its own command line.
    for cmdline in $(grep -l 'okumakayd[i]\.sh' /proc/[0-9]*/cmdline 2>/dev/null); do
        pid=${cmdline#/proc/}
        kill "${pid%/cmdline}" 2>/dev/null
    done
    rm -rf "$LEGACY_DIR" "$LEGACY_RULE" /tmp/okumakaydi.kilit /tmp/okumakaydi.yeni /tmp/okumakaydi.yeni.fark
}

move_legacy_records() {
    # The Mac side skips rows it has already imported, so appending is safe.
    [ -f "$LEGACY_OUT/kayit.tsv" ] && cat "$LEGACY_OUT/kayit.tsv" >> "$OUT/history.tsv"
    [ -f "$LEGACY_OUT/okumakaydi.log" ] && cat "$LEGACY_OUT/okumakaydi.log" >> "$OUT/logger.log"
    rm -rf "$LEGACY_OUT"
    log "moved the records of the previous version from $LEGACY_OUT"
}

snapshot() {
    "$SQLITE" -readonly -noheader -separator "$TAB" -cmd '.timeout 10000' "$DB" \
        "SELECT ContentID, TimeSpentReading, ___PercentRead, ReadStatus, COALESCE(DateLastRead, ''),
                replace(replace(replace(COALESCE(Title, ''), char(9), ' '), char(10), ' '), char(13), ' ')
         FROM content
         WHERE ContentType = 6 AND (TimeSpentReading > 0 OR ReadStatus > 0)
         ORDER BY ContentID;"
}

started=0
last_heartbeat=0
round=0

while true; do
    if [ "$round" -lt "$LEGACY_ROUNDS" ]; then
        round=$((round + 1))
        remove_legacy_logger
    fi

    if onboard_mounted && [ -f "$DB" ]; then
        mkdir -p "$OUT"
        [ -f "$OUT/UNINSTALL" ] && uninstall
        [ -d "$LEGACY_OUT" ] && move_legacy_records
        now=$(date +%s)

        if [ "$started" = 0 ]; then
            log "started (version $VERSION, pid $$, $(cat /mnt/onboard/.kobo/version 2>/dev/null))"
            started=1
        fi

        if snapshot > "$SNAPSHOT" 2>>"$OUT/logger.log" && [ -s "$SNAPSHOT" ]; then
            touch "$OUT/last-state.tsv"
            # Append only the rows that differ from the previous round.
            awk -F"$TAB" -v ts="$now" '
                FILENAME == ARGV[1] { previous[$0] = 1; next }
                !($0 in previous) { print ts "\t" $0 }
            ' "$OUT/last-state.tsv" "$SNAPSHOT" > "$SNAPSHOT.diff"
            if [ -s "$SNAPSHOT.diff" ]; then
                cat "$SNAPSHOT.diff" >> "$OUT/history.tsv"
            fi
            cp "$SNAPSHOT" "$OUT/last-state.tsv.tmp" && mv "$OUT/last-state.tsv.tmp" "$OUT/last-state.tsv"
            rm -f "$SNAPSHOT.diff"
        fi

        # An hourly heartbeat so the Mac side can tell the logger is alive.
        if [ $((now - last_heartbeat)) -ge 3600 ]; then
            echo "$now" > "$OUT/heartbeat"
            last_heartbeat=$now
        fi
    fi
    sleep "$INTERVAL"
done

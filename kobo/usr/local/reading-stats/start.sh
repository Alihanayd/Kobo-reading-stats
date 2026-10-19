#!/bin/sh
# Called by udev. udev kills long-running processes, so this first detaches itself,
# then starts logger.sh unless it's already running.

if [ "$READING_STATS_DETACHED" != "1" ]; then
    READING_STATS_DETACHED=1 setsid "$0" "$@" </dev/null >/dev/null 2>&1 &
    exit 0
fi

cd /
LOCK=/tmp/reading-stats.lock

is_running() {
    pid=$(cat "$LOCK/pid" 2>/dev/null)
    [ -n "$pid" ] && grep -q reading-stats "/proc/$pid/cmdline" 2>/dev/null
}

if ! mkdir "$LOCK" 2>/dev/null; then
    # Several triggers can arrive at once during boot; wait for the other one to write its pid.
    sleep 3
    is_running && exit 0
    # The lock was left over from an earlier boot; take it over.
fi
echo $$ > "$LOCK/pid"
exec /bin/sh /usr/local/reading-stats/logger.sh

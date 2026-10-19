#!/bin/sh
# udev tarafından çağrılır. udev uzun süren işlemleri öldürdüğü için önce kendini ayırır,
# sonra okumakaydi.sh zaten çalışmıyorsa onu başlatır.

if [ "$OKUMAKAYDI_AYRIK" != "1" ]; then
    OKUMAKAYDI_AYRIK=1 setsid "$0" "$@" </dev/null >/dev/null 2>&1 &
    exit 0
fi

cd /
KILIT=/tmp/okumakaydi.kilit

calisiyor_mu() {
    pid=$(cat "$KILIT/pid" 2>/dev/null)
    [ -n "$pid" ] && grep -q okumakaydi "/proc/$pid/cmdline" 2>/dev/null
}

if ! mkdir "$KILIT" 2>/dev/null; then
    # Açılışta birkaç tetikleyici aynı anda gelebilir; diğerinin pid yazmasını bekle.
    sleep 3
    calisiyor_mu && exit 0
    # Kilit eski bir açılıştan kalmış, devral.
fi
echo $$ > "$KILIT/pid"
exec /bin/sh /usr/local/okumakaydi/okumakaydi.sh

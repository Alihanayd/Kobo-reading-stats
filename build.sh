#!/bin/sh
# Kobo'ya kurulacak KoboRoot.tgz paketini üretir.
#   1. Zig ve SQLite kaynak kodunu (yoksa) build/ altına indirir, imzalarını doğrular.
#   2. SQLite komut satırı aracını Kobo'nun ARM işlemcisi için statik olarak derler.
#   3. kobo/ altındaki dosyaları root sahipliğinde, macOS ek dosyaları olmadan paketler.
set -eu

KOK=$(cd "$(dirname "$0")" && pwd)
B=$KOK/build

ZIG_SURUM=0.17.0
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)
        ZIG_PLATFORM=aarch64-macos
        ZIG_SHA256=b607e9b9234790a008116ae5bdb71c6243b84b9fb42a53a9e70fde41c06c536a ;;
    Darwin-x86_64)
        ZIG_PLATFORM=x86_64-macos
        ZIG_SHA256=4f9a1c5269aa17ebda5e6d3c2b89d6cbf36f7d2b22a0306e9ab98f25f95529c6 ;;
    *)
        echo "Bu betik macOS (Apple Silicon ya da Intel) için yazıldı." >&2
        exit 1 ;;
esac
SQLITE_DOSYA=sqlite-amalgamation-3540000
SQLITE_URL=https://sqlite.org/2026/$SQLITE_DOSYA.zip
SQLITE_SHA3=7b670a62fdfbd672b75fef004cb703c8a3e87d3a5cc7d675b4a08337004a2d93

mkdir -p "$B"

ZIG=$B/zig-$ZIG_PLATFORM-$ZIG_SURUM/zig
HEDEF=$KOK/kobo/usr/local/okumakaydi/sqlite3

# sqlite3 zaten derlenmişse derleyiciye ve kaynak koda gerek yok.
if [ ! -f "$HEDEF" ]; then
    if [ ! -x "$ZIG" ]; then
        echo "Zig indiriliyor..."
        curl -sSL -o "$B/zig.tar.xz" "https://ziglang.org/download/$ZIG_SURUM/zig-$ZIG_PLATFORM-$ZIG_SURUM.tar.xz"
        echo "$ZIG_SHA256  $B/zig.tar.xz" | shasum -a 256 -c -
        tar -xf "$B/zig.tar.xz" -C "$B"
        rm "$B/zig.tar.xz"
    fi

    if [ ! -f "$B/$SQLITE_DOSYA/sqlite3.c" ]; then
        echo "SQLite indiriliyor..."
        curl -sSL -o "$B/sqlite.zip" "$SQLITE_URL"
        # sqlite.org SHA3-256 yayınlıyor.
        [ "$(python3 -I -c 'import hashlib,sys; print(hashlib.sha3_256(open(sys.argv[1],"rb").read()).hexdigest())' "$B/sqlite.zip")" = "$SQLITE_SHA3" ]
        unzip -q -o "$B/sqlite.zip" -d "$B"
        rm "$B/sqlite.zip"
    fi

    echo "sqlite3 Kobo (ARMv7) için derleniyor..."
    "$ZIG" cc -target arm-linux-musleabihf -mcpu=cortex_a7 -static -Os -s \
        -DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION -DSQLITE_DEFAULT_MEMSTATUS=0 -DHAVE_USLEEP=1 \
        -o "$HEDEF" "$B/$SQLITE_DOSYA/shell.c" "$B/$SQLITE_DOSYA/sqlite3.c"
fi

chmod 755 "$KOK"/kobo/usr/local/okumakaydi/*
chmod 644 "$KOK"/kobo/etc/udev/rules.d/98-okumakaydi.rules

# Sadece kendi dosyalarımızı ve kendi klasörümüzü paketliyoruz; /etc, /usr gibi mevcut
# klasörlerin izinlerine dokunmamak için onların kayıtlarını pakete koymuyoruz.
COPYFILE_DISABLE=1 tar -c -z -n -f "$B/KoboRoot.tgz" -C "$KOK/kobo" \
    --format ustar --uid 0 --gid 0 --uname root --gname root --no-mac-metadata --no-xattrs \
    usr/local/okumakaydi/ \
    usr/local/okumakaydi/sqlite3 \
    usr/local/okumakaydi/baslat.sh \
    usr/local/okumakaydi/okumakaydi.sh \
    etc/udev/rules.d/98-okumakaydi.rules

echo "Hazır: $B/KoboRoot.tgz"
tar -tvzf "$B/KoboRoot.tgz"

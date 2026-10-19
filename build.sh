#!/bin/sh
# Builds the KoboRoot.tgz package that installs the logger on the Kobo.
#   1. Downloads Zig and the SQLite source into build/ (if missing) and verifies their hashes.
#   2. Builds the SQLite command-line tool statically for the Kobo's ARM processor.
#   3. Packs the files under kobo/ owned by root, without macOS metadata files.
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
BUILD=$ROOT/build

ZIG_VERSION=0.17.0
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)
        ZIG_PLATFORM=aarch64-macos
        ZIG_SHA256=b607e9b9234790a008116ae5bdb71c6243b84b9fb42a53a9e70fde41c06c536a ;;
    Darwin-x86_64)
        ZIG_PLATFORM=x86_64-macos
        ZIG_SHA256=4f9a1c5269aa17ebda5e6d3c2b89d6cbf36f7d2b22a0306e9ab98f25f95529c6 ;;
    *)
        echo "This script is meant for macOS (Apple Silicon or Intel)." >&2
        exit 1 ;;
esac
SQLITE_NAME=sqlite-amalgamation-3540000
SQLITE_URL=https://sqlite.org/2026/$SQLITE_NAME.zip
SQLITE_SHA3=7b670a62fdfbd672b75fef004cb703c8a3e87d3a5cc7d675b4a08337004a2d93

mkdir -p "$BUILD"

ZIG=$BUILD/zig-$ZIG_PLATFORM-$ZIG_VERSION/zig
TARGET=$ROOT/kobo/usr/local/reading-stats/sqlite3

# Once sqlite3 is built, the compiler and the source aren't needed.
if [ ! -f "$TARGET" ]; then
    if [ ! -x "$ZIG" ]; then
        echo "Downloading Zig..."
        curl -sSL -o "$BUILD/zig.tar.xz" "https://ziglang.org/download/$ZIG_VERSION/zig-$ZIG_PLATFORM-$ZIG_VERSION.tar.xz"
        echo "$ZIG_SHA256  $BUILD/zig.tar.xz" | shasum -a 256 -c -
        tar -xf "$BUILD/zig.tar.xz" -C "$BUILD"
        rm "$BUILD/zig.tar.xz"
    fi

    if [ ! -f "$BUILD/$SQLITE_NAME/sqlite3.c" ]; then
        echo "Downloading SQLite..."
        curl -sSL -o "$BUILD/sqlite.zip" "$SQLITE_URL"
        # sqlite.org publishes SHA3-256 hashes.
        [ "$(python3 -I -c 'import hashlib,sys; print(hashlib.sha3_256(open(sys.argv[1],"rb").read()).hexdigest())' "$BUILD/sqlite.zip")" = "$SQLITE_SHA3" ]
        unzip -q -o "$BUILD/sqlite.zip" -d "$BUILD"
        rm "$BUILD/sqlite.zip"
    fi

    echo "Building sqlite3 for the Kobo (ARMv7)..."
    "$ZIG" cc -target arm-linux-musleabihf -mcpu=cortex_a7 -static -Os -s \
        -DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION -DSQLITE_DEFAULT_MEMSTATUS=0 -DHAVE_USLEEP=1 \
        -o "$TARGET" "$BUILD/$SQLITE_NAME/shell.c" "$BUILD/$SQLITE_NAME/sqlite3.c"
fi

chmod 755 "$ROOT"/kobo/usr/local/reading-stats/*
chmod 644 "$ROOT"/kobo/etc/udev/rules.d/98-reading-stats.rules

# Only our own files and our own folder go into the package. Existing folders such as /etc
# and /usr are left out so their permissions on the device aren't touched.
COPYFILE_DISABLE=1 tar -c -z -n -f "$BUILD/KoboRoot.tgz" -C "$ROOT/kobo" \
    --format ustar --uid 0 --gid 0 --uname root --gname root --no-mac-metadata --no-xattrs \
    usr/local/reading-stats/ \
    usr/local/reading-stats/sqlite3 \
    usr/local/reading-stats/start.sh \
    usr/local/reading-stats/logger.sh \
    etc/udev/rules.d/98-reading-stats.rules

echo "Done: $BUILD/KoboRoot.tgz"
tar -tvzf "$BUILD/KoboRoot.tgz"

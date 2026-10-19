#!/usr/bin/env python3
"""Kobo reading stats.

Imports the records kept by the logger on the Kobo (and a snapshot of Kobo's own database),
collects them in a local database and builds data/dashboard.html.

Usage:
  python3 kobo_stats.py              import from the Kobo if it's plugged in, build and open the dashboard
  python3 kobo_stats.py --auto       for launchd: exit quietly if no Kobo is plugged in, update the
                                     dashboard without opening it, show a notification
  python3 kobo_stats.py --dashboard  rebuild and open the dashboard without looking for the Kobo

Interface language (dashboard, notifications, console): KOBO_STATS_LANG=en|tr, otherwise macOS.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("KOBO_STATS_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "reading.db"
DASHBOARD = DATA_DIR / "dashboard.html"
TEMPLATE = Path(__file__).resolve().parent / "dashboard_template.html"

KOBO = Path("/Volumes/KOBOeReader")
KOBO_DB = KOBO / ".kobo" / "KoboReader.sqlite"
KOBO_LOG_DIR = KOBO / ".adds" / "reading-stats"

# The logger writes a heartbeat every hour while it runs; if the last read is much later
# than the heartbeat, the logger has stopped.
HEARTBEAT_TOLERANCE = 2 * 3600

# Text the user sees. The dashboard's own text lives in dashboard_template.html; the
# language reaches it through the "lang" field of the embedded data.
STRINGS = {
    "en": {
        "description": ("Kobo reading stats: if the Kobo is plugged in, imports its records, "
                        "then builds and opens the dashboard."),
        "help_auto": "launchd mode: exit quietly if no Kobo is plugged in, update the "
                     "dashboard without opening it, show a notification",
        "help_dashboard": "rebuild and open the dashboard without looking for the Kobo",
        "notification_title": "Kobo Reading Stats",
        "logger_never_ran": ("The logger on the Kobo has never run. Setup may be incomplete: "
                             "copy KoboRoot.tgz to the .kobo folder and eject the Kobo."),
        "logger_stopped": ("The logger on the Kobo seems to have stopped on {date}. A Kobo "
                           "firmware update may have removed it; copy build/KoboRoot.tgz to the "
                           ".kobo folder again and eject the Kobo."),
        "date_format": "%Y-%m-%d %H:%M",
        "permission_error": "permission error: {error}",
        "permission_notification": ("No permission to read the files on the Kobo. In System "
                                    "Settings > Privacy & Security > Files & Folders, give Kobo "
                                    "Reading Stats access to Removable Volumes."),
        "imported": "Imported from the Kobo: {log_rows} new log rows, {snapshot_rows} snapshot rows.",
        "warning": "WARNING:",
        "not_plugged_in": "The Kobo isn't plugged in; building the dashboard from existing data.",
        "no_data": "No data yet. Plug in the Kobo and run this again.",
        "dashboard_path": "Dashboard: {path}",
        "notification_today": "You read for {duration} today. Dashboard updated.",
        "notification_warning": "Heads up: the logger on the Kobo may have stopped. Open the dashboard.",
        "minutes": "{m} min",
        "hours_minutes": "{h} h {m:02d} min",
    },
    "tr": {
        "description": ("Kobo okuma istatistikleri: Kobo takılıysa kayıtlarını alır, paneli "
                        "üretir ve açar."),
        "help_auto": "launchd modu: Kobo takılı değilse sessizce çık, paneli açmadan "
                     "güncelle, bildirim göster",
        "help_dashboard": "Kobo'ya bakmadan paneli yeniden üret ve aç",
        "notification_title": "Kobo Okuma İstatistikleri",
        "logger_never_ran": ("Kobo'daki kayıt betiği hiç çalışmamış. Kurulum tamamlanmamış "
                             "olabilir: KoboRoot.tgz'yi .kobo klasörüne kopyalayıp Kobo'yu çıkar."),
        "logger_stopped": ("Kobo'daki kayıt betiği {date} tarihinden beri çalışmıyor görünüyor. "
                           "Kobo yazılım güncellemesi betiği silmiş olabilir; build/KoboRoot.tgz'yi "
                           "yeniden .kobo klasörüne kopyalayıp Kobo'yu çıkar."),
        "date_format": "%d.%m.%Y %H:%M",
        "permission_error": "izin hatası: {error}",
        "permission_notification": ("Kobo'daki dosyalara erişim izni yok. Sistem Ayarları > "
                                    "Gizlilik ve Güvenlik > Dosyalar ve Klasörler'den Kobo Reading "
                                    "Stats'e Çıkarılabilir Birimler izni ver."),
        "imported": "Kobo'dan alındı: {log_rows} yeni kayıt, {snapshot_rows} anlık satır.",
        "warning": "UYARI:",
        "not_plugged_in": "Kobo takılı değil; mevcut verilerle panel üretiliyor.",
        "no_data": "Henüz veri yok. Kobo'yu takıp tekrar çalıştır.",
        "dashboard_path": "Panel: {path}",
        "notification_today": "Bugün {duration} okudun. Panel güncellendi.",
        "notification_warning": "Dikkat: kayıt betiği çalışmıyor olabilir. Paneli aç.",
        "minutes": "{m} dk",
        "hours_minutes": "{h} sa {m:02d} dk",
    },
}


def choose_language():
    """Uses KOBO_STATS_LANG (en/tr) if set, otherwise the first preferred macOS language:
    Turkish if the language is Turkish or the region is Turkey (tr-TR, en-TR), else English."""
    choice = os.environ.get("KOBO_STATS_LANG", "").strip().lower()[:2]
    if choice in STRINGS:
        return choice
    try:
        output = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                                text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return "en"
    # The output looks like "(\n    "en-TR",\n    "tr-TR"\n)"; the first item is the main choice.
    languages = [item.strip().strip('"') for item in output.strip().strip("()").split(",")]
    parts = (languages[0] if languages else "").replace("_", "-").split("-")
    if parts[0].lower() == "tr" or "TR" in (p.upper() for p in parts[1:]):
        return "tr"
    return "en"


LANG = choose_language()
TEXT = STRINGS[LANG]

SNAPSHOT_QUERY = """
SELECT ContentID, TimeSpentReading, ___PercentRead, ReadStatus, COALESCE(DateLastRead, ''),
       COALESCE(Title, '')
FROM content
WHERE ContentType = 6 AND (TimeSpentReading > 0 OR ReadStatus > 0)
"""


def open_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS samples (
            time INTEGER NOT NULL,        -- Unix seconds
            content_id TEXT NOT NULL,     -- Kobo ContentID
            seconds INTEGER NOT NULL,     -- TimeSpentReading
            percent INTEGER NOT NULL,
            status INTEGER NOT NULL,      -- 0 unread, 1 reading, 2 finished
            last_read TEXT,
            title TEXT,
            source TEXT NOT NULL,         -- 'device': the logger, 'snapshot': read on plug-in
            PRIMARY KEY (time, content_id)
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return db


def get_meta(db, key):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))


def import_device_log(db):
    """Reads history.tsv from the Kobo; returns the number of new rows."""
    path = KOBO_LOG_DIR / "history.tsv"
    if not path.exists():
        return None
    added = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 7:
                continue
            try:
                logged_at, content_id, seconds, percent, status = (
                    int(fields[0]), fields[1], int(fields[2]), int(fields[3]), int(fields[4]))
            except ValueError:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, 'device')",
                (logged_at, content_id, seconds, percent, status, fields[5], "\t".join(fields[6:])))
            added += cursor.rowcount
    return added


def import_snapshot(db):
    """Copies and reads Kobo's own database. This catches the last changes the logger missed
    (for example the book that was closed when the Kobo was plugged in). Adds the rows that
    differ from the latest sample."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "KoboReader.sqlite"
        shutil.copyfile(KOBO_DB, copy)
        wal = KOBO_DB.with_name(KOBO_DB.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, copy.with_name(copy.name + "-wal"))
        kobo = sqlite3.connect(copy)
        rows = kobo.execute(SNAPSHOT_QUERY).fetchall()
        kobo.close()

    now = int(time.time())
    added = 0
    for content_id, seconds, percent, status, last_read, title in rows:
        latest = db.execute(
            "SELECT seconds, percent, status, last_read FROM samples WHERE content_id = ? "
            "ORDER BY time DESC LIMIT 1", (content_id,)).fetchone()
        if latest == (seconds, percent, status, last_read):
            continue
        db.execute("INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, 'snapshot')",
                   (now, content_id, seconds, percent, status, last_read, title))
        added += 1
    return rows, added


def parse_kobo_time(text):
    """Converts Kobo's DateLastRead (UTC, sometimes without a 'Z') to Unix seconds."""
    if not text:
        return None
    text = text.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    return None


def logger_health(snapshot_rows):
    """Guesses whether the logger on the plugged-in Kobo is running. Returns a message if not."""
    if not (KOBO_LOG_DIR / "history.tsv").exists():
        return TEXT["logger_never_ran"]
    try:
        heartbeat = int((KOBO_LOG_DIR / "heartbeat").read_text().strip())
    except (OSError, ValueError):
        return None
    last_read = max((parse_kobo_time(row[4]) or 0 for row in snapshot_rows), default=0)
    if last_read - heartbeat > HEARTBEAT_TOLERANCE:
        when = datetime.fromtimestamp(heartbeat).strftime(TEXT["date_format"])
        return TEXT["logger_stopped"].format(date=when)
    return None


# --- Calculation -------------------------------------------------------------------------

def spread_over_days(end, seconds, daily, hourly=None):
    """Splits the reading in [end - seconds, end] into local days (and hours)."""
    t = end - seconds
    while t < end:
        local = datetime.fromtimestamp(t)
        next_hour = (local.replace(minute=0, second=0, microsecond=0)
                     + timedelta(hours=1)).timestamp()
        chunk = min(end, next_hour) - t
        daily[local.date()] += chunk
        if hourly is not None:
            hourly[local.hour] += chunk
        t += chunk


def compute(db):
    tracking_start = int(get_meta(db, "tracking_start"))
    samples = defaultdict(list)
    for row in db.execute("SELECT time, content_id, seconds, percent, status, last_read, title "
                          "FROM samples ORDER BY time"):
        samples[row[1]].append(row)

    daily_total = defaultdict(float)
    daily_by_book = defaultdict(lambda: defaultdict(float))
    hourly = defaultdict(float)
    books = []

    for content_id, rows in samples.items():
        previous = None
        tracked = 0.0
        finished_on = None
        for logged_at, _, seconds, percent, status, last_read, title in rows:
            if logged_at <= tracking_start:
                # Time that already existed when tracking started: history, not spread over days.
                previous = (seconds, status, logged_at)
                continue
            prev_seconds, prev_status, prev_time = previous if previous else (0, 0, None)
            delta = seconds - prev_seconds
            if delta < 0:  # the book was reset and is being read from the start
                delta = seconds
            # When the reading ended: Kobo's last-read time, unless it wasn't updated with this
            # change (it's older than the previous sample); then the time the sample was taken.
            end = parse_kobo_time(last_read)
            if (end is None or end > logged_at + 120
                    or (prev_time is not None and end < prev_time - 120)):
                end = logged_at
            if delta > 0:
                book_days = defaultdict(float)
                spread_over_days(end, delta, book_days, hourly)
                for day, secs in book_days.items():
                    daily_total[day] += secs
                    daily_by_book[day][content_id] += secs
                tracked += delta
            if status == 2 and prev_status != 2:
                finished_on = datetime.fromtimestamp(end).date().isoformat()
            previous = (seconds, status, logged_at)

        _, _, seconds, percent, status, last_read, title = rows[-1]
        last = parse_kobo_time(last_read)
        speed = percent / (seconds / 3600) if seconds >= 900 and 0 < percent < 100 else None
        books.append({
            "id": content_id,
            "title": title or content_id.rsplit("/", 1)[-1],
            "total": seconds,
            "tracked": round(tracked),
            "percent": percent,
            "status": status,
            "last_read": datetime.fromtimestamp(last).isoformat(timespec="minutes") if last else None,
            "finished_on": finished_on,
            "time_left": round((100 - percent) / speed * 3600) if speed else None,
        })

    books.sort(key=lambda b: (b["status"] == 2, -iso_timestamp(b["last_read"])))
    titles = {b["id"]: b["title"] for b in books}

    today = date.today()
    days = []
    day = datetime.fromtimestamp(tracking_start).date()
    while day <= today:
        days.append({
            "date": day.isoformat(),
            "seconds": round(daily_total.get(day, 0)),
            "books": sorted(
                ({"title": titles.get(i, i), "seconds": round(s)}
                 for i, s in daily_by_book.get(day, {}).items() if s >= 30),
                key=lambda b: -b["seconds"]),
        })
        day += timedelta(days=1)

    return {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "tracking_start": datetime.fromtimestamp(tracking_start).isoformat(timespec="minutes"),
        "days": days,
        "hourly": [round(hourly.get(h, 0)) for h in range(24)],
        "books": books,
        "kobo_total": sum(b["total"] for b in books),
        "warning": get_meta(db, "warning"),
        "last_import": get_meta(db, "last_import"),
        "lang": LANG,
    }


def iso_timestamp(text):
    return datetime.fromisoformat(text).timestamp() if text else 0


def write_dashboard(data):
    template = TEMPLATE.read_text(encoding="utf-8")
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    DASHBOARD.write_text(template.replace("/*DATA*/null", embedded), encoding="utf-8")


def notify(message):
    # AppleScript doesn't understand \u escapes, so non-ASCII text must stay as it is.
    message, title = (json.dumps(s, ensure_ascii=False) for s in (message, TEXT["notification_title"]))
    script = f"display notification {message} with title {title}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def format_duration(seconds):
    minutes = round(seconds / 60)
    if minutes >= 60:
        return TEXT["hours_minutes"].format(h=minutes // 60, m=minutes % 60)
    return TEXT["minutes"].format(m=minutes)


def main():
    parser = argparse.ArgumentParser(description=TEXT["description"],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--auto", action="store_true", help=TEXT["help_auto"])
    parser.add_argument("--dashboard", action="store_true", help=TEXT["help_dashboard"])
    args = parser.parse_args()

    db = open_db()
    try:
        kobo_plugged_in = KOBO_DB.exists()
    except PermissionError:
        kobo_plugged_in = True  # plugged in but not readable; reported below

    if args.auto and not kobo_plugged_in:
        return 0

    if kobo_plugged_in and not args.dashboard:
        try:
            new_log_rows = import_device_log(db)
            snapshot, new_snapshot_rows = import_snapshot(db)
        except PermissionError as error:
            print(f"{datetime.now():%Y-%m-%d %H:%M}", TEXT["permission_error"].format(error=error),
                  file=sys.stderr)
            notify(TEXT["permission_notification"])
            return 1
        if get_meta(db, "tracking_start") is None:
            first = db.execute("SELECT MIN(time) FROM samples").fetchone()[0]
            if first is not None:
                set_meta(db, "tracking_start", first)
        warning = logger_health(snapshot)
        set_meta(db, "warning", warning or "")
        set_meta(db, "last_import", datetime.now().isoformat(timespec="minutes"))
        db.commit()
        print(TEXT["imported"].format(log_rows=new_log_rows or 0, snapshot_rows=new_snapshot_rows))
        if warning:
            print(TEXT["warning"], warning)
    elif not kobo_plugged_in and not args.dashboard:
        print(TEXT["not_plugged_in"])

    if get_meta(db, "tracking_start") is None:
        print(TEXT["no_data"])
        return 0

    data = compute(db)
    write_dashboard(data)
    print(TEXT["dashboard_path"].format(path=DASHBOARD))

    today = data["days"][-1]["seconds"] if data["days"] else 0
    if args.auto:
        message = TEXT["notification_today"].format(duration=format_duration(today))
        if data["warning"]:
            message = TEXT["notification_warning"]
        notify(message)
    else:
        subprocess.run(["open", str(DASHBOARD)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

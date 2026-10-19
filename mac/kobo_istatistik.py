#!/usr/bin/env python3
"""Kobo okuma istatistikleri.

Kobo'daki okumakaydi betiğinin tuttuğu kayıtları (ve Kobo'nun kendi veritabanını) alır,
kendi veritabanında biriktirir ve veri/panel.html sayfasını üretir.

Kullanım:
  python3 kobo_istatistik.py             Kobo takılıysa kayıtları al, paneli üret ve aç
  python3 kobo_istatistik.py --otomatik  launchd için: Kobo takılı değilse sessizce çık,
                                         paneli açmadan güncelle, bildirim göster
  python3 kobo_istatistik.py --panel     Kobo'ya bakmadan paneli yeniden üret ve aç
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

KOK = Path(__file__).resolve().parent.parent
VERI = Path(os.environ.get("KOBO_ISTATISTIK_VERI", KOK / "veri"))
DB_YOLU = VERI / "okuma.db"
PANEL = VERI / "panel.html"
SABLON = Path(__file__).resolve().parent / "panel_sablon.html"

KOBO = Path("/Volumes/KOBOeReader")
KOBO_DB = KOBO / ".kobo" / "KoboReader.sqlite"
KOBO_KAYIT = KOBO / ".adds" / "okumakaydi"

# Betik canlıyken saatte bir nabız yazar; son okuma bundan çok sonraysa betik çalışmıyordur.
NABIZ_TOLERANSI = 2 * 3600

ANLIK_SORGU = """
SELECT ContentID, TimeSpentReading, ___PercentRead, ReadStatus, COALESCE(DateLastRead, ''),
       COALESCE(Title, '')
FROM content
WHERE ContentType = 6 AND (TimeSpentReading > 0 OR ReadStatus > 0)
"""


def veritabani():
    VERI.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_YOLU)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS ornekler (
            zaman INTEGER NOT NULL,   -- unix saniye
            icerik TEXT NOT NULL,     -- Kobo ContentID
            sure INTEGER NOT NULL,    -- TimeSpentReading, saniye
            yuzde INTEGER NOT NULL,
            durum INTEGER NOT NULL,   -- 0 okunmadı, 1 okunuyor, 2 bitti
            son_okuma TEXT,
            baslik TEXT,
            kaynak TEXT NOT NULL,     -- 'kobo': cihazdaki betik, 'usb': takınca doğrudan okunan
            PRIMARY KEY (zaman, icerik)
        );
        CREATE TABLE IF NOT EXISTS meta (anahtar TEXT PRIMARY KEY, deger TEXT);
    """)
    return db


def meta_al(db, anahtar):
    satir = db.execute("SELECT deger FROM meta WHERE anahtar = ?", (anahtar,)).fetchone()
    return satir[0] if satir else None


def meta_yaz(db, anahtar, deger):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (anahtar, str(deger)))


def cihaz_kaydini_al(db):
    """Kobo'daki kayit.tsv'yi okur; yeni satır sayısını döndürür."""
    yol = KOBO_KAYIT / "kayit.tsv"
    if not yol.exists():
        return None
    eklenen = 0
    with open(yol, encoding="utf-8", errors="replace") as f:
        for satir in f:
            parca = satir.rstrip("\n").split("\t")
            if len(parca) < 7:
                continue
            try:
                zaman, icerik, sure, yuzde, durum = (int(parca[0]), parca[1], int(parca[2]),
                                                     int(parca[3]), int(parca[4]))
            except ValueError:
                continue
            imlec = db.execute(
                "INSERT OR IGNORE INTO ornekler VALUES (?, ?, ?, ?, ?, ?, ?, 'kobo')",
                (zaman, icerik, sure, yuzde, durum, parca[5], "\t".join(parca[6:])))
            eklenen += imlec.rowcount
    return eklenen


def kobo_anlik_al(db):
    """Kobo'nun kendi veritabanını kopyalayıp okur. Betiğin kaçırdığı son değişiklikleri
    (örneğin USB'ye takarken kapanan kitabı) yakalar. Son kayıttan farklı satırları ekler."""
    with tempfile.TemporaryDirectory() as gecici:
        kopya = Path(gecici) / "KoboReader.sqlite"
        shutil.copyfile(KOBO_DB, kopya)
        wal = KOBO_DB.with_name(KOBO_DB.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, kopya.with_name(kopya.name + "-wal"))
        kobo = sqlite3.connect(kopya)
        satirlar = kobo.execute(ANLIK_SORGU).fetchall()
        kobo.close()

    simdi = int(time.time())
    eklenen = 0
    for icerik, sure, yuzde, durum, son_okuma, baslik in satirlar:
        son = db.execute(
            "SELECT sure, yuzde, durum, son_okuma FROM ornekler WHERE icerik = ? "
            "ORDER BY zaman DESC LIMIT 1", (icerik,)).fetchone()
        if son == (sure, yuzde, durum, son_okuma):
            continue
        db.execute("INSERT OR IGNORE INTO ornekler VALUES (?, ?, ?, ?, ?, ?, ?, 'usb')",
                   (simdi, icerik, sure, yuzde, durum, son_okuma, baslik))
        eklenen += 1
    return satirlar, eklenen


def kobo_zamani(metin):
    """Kobo'nun DateLastRead değerini (UTC, bazen 'Z'siz) unix saniyeye çevirir."""
    if not metin:
        return None
    metin = metin.rstrip("Z")
    for bicim in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(metin, bicim).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    return None


def betik_sagligi(anlik_satirlar):
    """Takılı Kobo'daki betiğin çalışıp çalışmadığını tahmin eder. Sorun varsa açıklama döndürür."""
    if not (KOBO_KAYIT / "kayit.tsv").exists():
        return ("Kobo'daki kayıt betiği hiç çalışmamış. Kurulum tamamlanmamış olabilir: "
                "KoboRoot.tgz'yi .kobo klasörüne kopyalayıp Kobo'yu çıkar.")
    try:
        nabiz = int((KOBO_KAYIT / "nabiz").read_text().strip())
    except (OSError, ValueError):
        return None
    son_okuma = max((kobo_zamani(s[4]) or 0 for s in anlik_satirlar), default=0)
    if son_okuma - nabiz > NABIZ_TOLERANSI:
        tarih = datetime.fromtimestamp(nabiz).strftime("%d.%m.%Y %H:%M")
        return (f"Kobo'daki kayıt betiği {tarih} tarihinden beri çalışmıyor görünüyor. "
                "Kobo yazılım güncellemesi betiği silmiş olabilir; build/KoboRoot.tgz'yi "
                "yeniden .kobo klasörüne kopyalayıp Kobo'yu çıkar.")
    return None


# --- Hesaplama -------------------------------------------------------------------------

def gune_dagit(bitis, saniye, gunluk, saatlik=None):
    """[bitis - saniye, bitis] aralığındaki okumayı yerel günlere (ve saatlere) böler."""
    baslangic = bitis - saniye
    t = baslangic
    while t < bitis:
        yerel = datetime.fromtimestamp(t)
        sonraki_saat = (yerel.replace(minute=0, second=0, microsecond=0)
                        + timedelta(hours=1)).timestamp()
        parca = min(bitis, sonraki_saat) - t
        gunluk[yerel.date()] += parca
        if saatlik is not None:
            saatlik[yerel.hour] += parca
        t += parca


def hesapla(db):
    takip_baslangic = int(meta_al(db, "takip_baslangic"))
    ornekler = defaultdict(list)
    for satir in db.execute("SELECT zaman, icerik, sure, yuzde, durum, son_okuma, baslik "
                            "FROM ornekler ORDER BY zaman"):
        ornekler[satir[1]].append(satir)

    gunluk_toplam = defaultdict(float)
    gunluk_kitap = defaultdict(lambda: defaultdict(float))
    saatlik = defaultdict(float)
    kitaplar = []

    for icerik, liste in ornekler.items():
        onceki = None
        takipte = 0.0
        bitis_tarihi = None
        for zaman, _, sure, yuzde, durum, son_okuma, baslik in liste:
            if zaman <= takip_baslangic:
                # Takip başladığında zaten var olan süre: geçmiş, günlere dağıtılmaz.
                onceki = (sure, durum, zaman)
                continue
            onceki_sure, onceki_durum, onceki_zaman = onceki if onceki else (0, 0, None)
            fark = sure - onceki_sure
            if fark < 0:  # kitap sıfırlanmış, baştan okunuyor
                fark = sure
            # Okumanın bittiği an: Kobo'nun son okuma zamanı, ama bu değişiklikle birlikte
            # güncellenmemişse (önceki örnekten eskiyse) örneğin alındığı an.
            bitis = kobo_zamani(son_okuma)
            if (bitis is None or bitis > zaman + 120
                    or (onceki_zaman is not None and bitis < onceki_zaman - 120)):
                bitis = zaman
            if fark > 0:
                kitap_gunu = defaultdict(float)
                gune_dagit(bitis, fark, kitap_gunu, saatlik)
                for gun, sn in kitap_gunu.items():
                    gunluk_toplam[gun] += sn
                    gunluk_kitap[gun][icerik] += sn
                takipte += fark
            if durum == 2 and onceki_durum != 2:
                bitis_tarihi = datetime.fromtimestamp(bitis).date().isoformat()
            onceki = (sure, durum, zaman)

        _, _, sure, yuzde, durum, son_okuma, baslik = liste[-1]
        son = kobo_zamani(son_okuma)
        hiz = yuzde / (sure / 3600) if sure >= 900 and 0 < yuzde < 100 else None
        kitaplar.append({
            "id": icerik,
            "baslik": baslik or icerik.rsplit("/", 1)[-1],
            "toplam": sure,
            "takipte": round(takipte),
            "yuzde": yuzde,
            "durum": durum,
            "son_okuma": datetime.fromtimestamp(son).isoformat(timespec="minutes") if son else None,
            "bitis": bitis_tarihi,
            "kalan_tahmin": round((100 - yuzde) / hiz * 3600) if hiz else None,
        })

    kitaplar.sort(key=lambda k: (k["durum"] == 2, -iso_zaman(k["son_okuma"])))
    basliklar = {k["id"]: k["baslik"] for k in kitaplar}

    bugun = date.today()
    ilk_gun = datetime.fromtimestamp(takip_baslangic).date()
    gunler = []
    g = ilk_gun
    while g <= bugun:
        gunler.append({
            "tarih": g.isoformat(),
            "saniye": round(gunluk_toplam.get(g, 0)),
            "kitaplar": sorted(
                ({"baslik": basliklar.get(i, i), "saniye": round(s)}
                 for i, s in gunluk_kitap.get(g, {}).items() if s >= 30),
                key=lambda x: -x["saniye"]),
        })
        g += timedelta(days=1)

    return {
        "olusturma": datetime.now().isoformat(timespec="minutes"),
        "takip_baslangic": datetime.fromtimestamp(takip_baslangic).isoformat(timespec="minutes"),
        "gunler": gunler,
        "saatlik": [round(saatlik.get(s, 0)) for s in range(24)],
        "kitaplar": kitaplar,
        "kobo_toplam": sum(k["toplam"] for k in kitaplar),
        "uyari": meta_al(db, "uyari"),
        "son_aktarim": meta_al(db, "son_aktarim"),
    }


def iso_zaman(metin):
    return datetime.fromisoformat(metin).timestamp() if metin else 0


def panel_uret(veri):
    sablon = SABLON.read_text(encoding="utf-8")
    gomulu = json.dumps(veri, ensure_ascii=False).replace("</", "<\\/")
    PANEL.write_text(sablon.replace("/*VERI*/null", gomulu), encoding="utf-8")


def bildirim(mesaj):
    betik = f'display notification {json.dumps(mesaj)} with title "Kobo İstatistik"'
    subprocess.run(["osascript", "-e", betik], check=False, capture_output=True)


def sure_metni(saniye):
    dakika = round(saniye / 60)
    return f"{dakika // 60} sa {dakika % 60:02d} dk" if dakika >= 60 else f"{dakika} dk"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--otomatik", action="store_true", help="launchd modu")
    ap.add_argument("--panel", action="store_true", help="sadece paneli üret ve aç")
    args = ap.parse_args()

    db = veritabani()
    try:
        kobo_takili = KOBO_DB.exists()
    except PermissionError:
        kobo_takili = True  # takılı ama erişim izni yok; aşağıda bildirilecek

    if args.otomatik and not kobo_takili:
        return 0

    if kobo_takili and not args.panel:
        try:
            yeni_kayit = cihaz_kaydini_al(db)
            anlik, yeni_anlik = kobo_anlik_al(db)
        except PermissionError as hata:
            print(f"{datetime.now():%Y-%m-%d %H:%M} izin hatası: {hata}", file=sys.stderr)
            bildirim("Kobo'daki dosyalara erişim izni yok. Sistem Ayarları > Gizlilik ve Güvenlik "
                     "> Dosyalar ve Klasörler'den python3'e Çıkarılabilir Birimler izni ver.")
            return 1
        if meta_al(db, "takip_baslangic") is None:
            ilk = db.execute("SELECT MIN(zaman) FROM ornekler").fetchone()[0]
            if ilk is not None:
                meta_yaz(db, "takip_baslangic", ilk)
        uyari = betik_sagligi(anlik)
        meta_yaz(db, "uyari", uyari or "")
        meta_yaz(db, "son_aktarim", datetime.now().isoformat(timespec="minutes"))
        db.commit()
        print(f"Kobo'dan alındı: {yeni_kayit or 0} yeni kayıt, {yeni_anlik} anlık satır.")
        if uyari:
            print("UYARI:", uyari)
    elif not kobo_takili and not args.panel:
        print("Kobo takılı değil; mevcut verilerle panel üretiliyor.")

    if meta_al(db, "takip_baslangic") is None:
        print("Henüz veri yok. Kobo'yu takıp tekrar çalıştır.")
        return 0

    veri = hesapla(db)
    panel_uret(veri)
    print(f"Panel: {PANEL}")

    bugun = veri["gunler"][-1]["saniye"] if veri["gunler"] else 0
    if args.otomatik:
        mesaj = f"Bugün {sure_metni(bugun)} okudun. Panel güncellendi."
        if veri["uyari"]:
            mesaj = "Dikkat: kayıt betiği çalışmıyor olabilir. Paneli aç."
        bildirim(mesaj)
    else:
        subprocess.run(["open", str(PANEL)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

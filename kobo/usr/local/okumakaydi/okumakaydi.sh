#!/bin/sh
# Kobo'nun kitap başına tuttuğu toplam okuma sürelerini dakikada bir okur ve
# değişen satırları /mnt/onboard/.adds/okumakaydi/kayit.tsv dosyasına ekler.
#
# kayit.tsv sütunları (sekme ile ayrılmış):
#   kayıt zamanı (unix, UTC) | ContentID | TimeSpentReading (sn) | ___PercentRead |
#   ReadStatus (0 okunmadı, 1 okunuyor, 2 bitti) | DateLastRead | Title
#
# Kaldırmak için: Kobo'yu bilgisayara bağla, .adds/okumakaydi/KALDIR adında boş bir dosya oluştur,
# cihazı çıkar. Betik bir dakika içinde kendini siler.

SURUM=1
DIZIN=/usr/local/okumakaydi
SQLITE=$DIZIN/sqlite3
DB=/mnt/onboard/.kobo/KoboReader.sqlite
CIKTI=/mnt/onboard/.adds/okumakaydi
YENI=/tmp/okumakaydi.yeni
ARALIK=60
SEKME=$(printf '\t')

cd /

onboard_bagli() {
    # USB bağlıyken /mnt/onboard bilgisayara verilir; o sırada oraya yazmamalıyız.
    grep -q ' /mnt/onboard ' /proc/mounts
}

gunluk() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >> "$CIKTI/okumakaydi.log"
}

kaldir() {
    gunluk "KALDIR dosyası bulundu, kaldırılıyor"
    rm -f /etc/udev/rules.d/98-okumakaydi.rules
    rm -rf "$DIZIN" /tmp/okumakaydi.kilit "$YENI"
    mv "$CIKTI/KALDIR" "$CIKTI/KALDIRILDI" 2>/dev/null
    exit 0
}

anlik_durum() {
    "$SQLITE" -readonly -noheader -separator "$SEKME" -cmd '.timeout 10000' "$DB" \
        "SELECT ContentID, TimeSpentReading, ___PercentRead, ReadStatus, COALESCE(DateLastRead, ''),
                replace(replace(replace(COALESCE(Title, ''), char(9), ' '), char(10), ' '), char(13), ' ')
         FROM content
         WHERE ContentType = 6 AND (TimeSpentReading > 0 OR ReadStatus > 0)
         ORDER BY ContentID;"
}

basladi=0
son_nabiz=0

while true; do
    if onboard_bagli && [ -f "$DB" ]; then
        mkdir -p "$CIKTI"
        [ -f "$CIKTI/KALDIR" ] && kaldir
        simdi=$(date +%s)

        if [ "$basladi" = 0 ]; then
            gunluk "başladı (sürüm $SURUM, pid $$, $(cat /mnt/onboard/.kobo/version 2>/dev/null))"
            basladi=1
        fi

        if anlik_durum > "$YENI" 2>>"$CIKTI/okumakaydi.log" && [ -s "$YENI" ]; then
            touch "$CIKTI/son-durum.tsv"
            # Sadece bir önceki turdan farklı olan satırları ekle.
            awk -F"$SEKME" -v ts="$simdi" '
                FILENAME == ARGV[1] { onceki[$0] = 1; next }
                !($0 in onceki) { print ts "\t" $0 }
            ' "$CIKTI/son-durum.tsv" "$YENI" > "$YENI.fark"
            if [ -s "$YENI.fark" ]; then
                cat "$YENI.fark" >> "$CIKTI/kayit.tsv"
            fi
            cp "$YENI" "$CIKTI/son-durum.tsv.tmp" && mv "$CIKTI/son-durum.tsv.tmp" "$CIKTI/son-durum.tsv"
            rm -f "$YENI.fark"
        fi

        # Betiğin çalıştığını Mac tarafının görebilmesi için saatte bir nabız.
        if [ $((simdi - son_nabiz)) -ge 3600 ]; then
            echo "$simdi" > "$CIKTI/nabiz"
            son_nabiz=$simdi
        fi
    fi
    sleep "$ARALIK"
done

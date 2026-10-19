# Kobo okuma istatistikleri

[English](README.md) · **Türkçe**

Kobo Clara BW'de günlük ne kadar okuduğumu takip eden küçük bir sistem.

![Panel](docs/panel-light.png)

Kobo kitap başına sadece *toplam* okuma süresini tutuyor, gün gün geçmiş tutmuyor. Bu yüzden iki parça var:

1. **Kobo'daki kayıt betiği** (`kobo/`). Kobo açıkken dakikada bir Kobo'nun veritabanına bakar. Bir kitabın süresi, yüzdesi ya da durumu değiştiyse o satırı zaman damgasıyla `.adds/okumakaydi/kayit.tsv` dosyasına ekler. Wi-Fi ya da bilgisayar gerekmez, kayıtlar cihazda birikir.
2. **Mac tarafı** (`mac/`). Kobo Mac'e takılınca kayıtları `veri/okuma.db` veritabanına alır ve `veri/panel.html` sayfasını üretir. Sayfada bugün, bu hafta, bu ay, okuma serisi, 30 günlük grafik, takvim, okunan saatler ve kitap bazında ilerleme ile kalan süre tahmini var.

Docker ya da başka bir servis gerekmez. Mac tarafı macOS'un kendi Python'u (`/usr/bin/python3`) ile çalışır, ek paket kullanmaz.

## Kullanım

- Kobo'yu her zamanki gibi kullan.
- Ara sıra Mac'e tak. Kayıtlar kendiliğinden alınır ve bir bildirim gelir ("Bugün 45 dk okudun").
- Paneli görmek için Spotlight'tan **Kobo İstatistik**'i aç ya da `veri/panel.html`'i aç.

Kobo'yu ne kadar seyrek taktığın önemli değil, günlük ayrım cihazda yapılıyor.

## Kurulum

### Kobo

```sh
./build.sh                                        # build/KoboRoot.tgz üretir
cp -X build/KoboRoot.tgz /Volumes/KOBOeReader/.kobo/
```

Sonra Kobo'yu Mac'ten çıkar. Kobo paketi kurar ve yeniden başlar.

`build.sh` Zig derleyicisini ve SQLite kaynak kodunu `build/` altına indirir (imzaları doğrulanır). SQLite komut satırı aracını Kobo'nun ARM işlemcisi için statik olarak derler.

Pakete girenler:

| Cihazdaki yol | Ne işe yarar |
|---|---|
| `/etc/udev/rules.d/98-okumakaydi.rules` | Açılışta `baslat.sh`'yi çalıştırır |
| `/usr/local/okumakaydi/baslat.sh` | udev'den ayrılır, betiğin tek kopya çalışmasını sağlar |
| `/usr/local/okumakaydi/okumakaydi.sh` | Dakikada bir kayıt alan döngü |
| `/usr/local/okumakaydi/sqlite3` | Kobo'nun veritabanını salt-okunur sorgulamak için |

Cihazda üretilen dosyalar (`.adds/okumakaydi/`):

- `kayit.tsv`: Değişiklik kayıtları. Sütunlar: unix zamanı, ContentID, saniye, yüzde, durum, son okuma, başlık.
- `son-durum.tsv`: Bir önceki turun durumu (karşılaştırma için).
- `nabiz`: Betiğin en son çalıştığı an (saatte bir yazılır).
- `okumakaydi.log`: Başlangıç ve hata kayıtları.

### Mac

```sh
mac/kur.sh
```

Bu komut `~/Applications/Kobo İstatistik.app` uygulamasını oluşturur. Ayrıca herhangi bir disk bağlandığında bu uygulamayı `--otomatik` ile çalıştıran bir launchd görevi kurar (`~/Library/LaunchAgents/com.gurmehub.kobo-istatistik.plist`).

macOS arka plandaki Python'un çıkarılabilir disklere erişmesine izin vermiyor. Bu yüzden betik uygulama üzerinden çalışıyor. İlk seferde macOS "Kobo İstatistik çıkarılabilir birimdeki dosyalara erişmek istiyor" diye sorar; İzin Ver demek yeterli. Uygulama yeniden derlenirse (yani `kur.sh` tekrar çalıştırılırsa) bu izni yeniden ister.

## Nasıl hesaplanıyor?

- Takip başladığı andaki süreler "geçmiş" sayılır ve günlere dağıtılmaz.
- Sonraki her kayıtta süredeki artış, Kobo'nun "son okuma" zamanından geriye doğru o kadar süre olarak günlere ve saatlere bölünür. Bu sayede gece yarısını aşan okumalar da doğru günlere düşer.
- Kitap sıfırlanırsa (süre azalırsa) yeni süre baştan okunmuş sayılır.
- Kalan süre tahmini, kitabın şimdiye kadarki ortalama hızına göre (yüzde / saat) hesaplanır.

## Sorun giderme

- **Panelde "kayıt betiği çalışmıyor" uyarısı var:** Kobo yazılım güncellemeleri betiği silebilir. `build/KoboRoot.tgz`'yi tekrar `.kobo/` klasörüne kopyalayıp Kobo'yu çıkar.
- **Takınca bildirim gelmiyor:** `veri/otomatik.log` dosyasına bak. "izin hatası" yazıyorsa Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler'de Kobo İstatistik için "Çıkarılabilir Birimler"i aç.
- Elle çalıştırmak için: `python3 mac/kobo_istatistik.py` (Kobo takılıysa kayıtları alır, paneli açar) ya da `--panel` (sadece paneli üretir).

## Kaldırma

- **Kobo'dan:** Kobo'yu tak, `.adds/okumakaydi/` klasöründe `KALDIR` adında boş bir dosya oluştur, Kobo'yu çıkar. Betik bir dakika içinde kendi dosyalarını ve udev kuralını siler; dosyanın adı `KALDIRILDI` olur. Kayıtlar yerinde kalır.
- **Mac'ten:** `mac/kaldir.sh` uygulamayı ve launchd görevini kaldırır. `veri/` silinmez.

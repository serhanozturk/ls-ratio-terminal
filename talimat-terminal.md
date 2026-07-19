# SERHAN — LS RATIO TERMINAL (Proje Talimatlari)

## ==========================================================
## #1 KIRMIZI CIZGI — BINANCE BAN (HER SEYIN ONUNDE)
## ==========================================================
BINANCE BAN BIZIM KIRMIZI CIZGIMIZDIR. Kod yazarken, guncellerken veya
ozellik eklerken HER ZAMAN once "bu degisiklik ban yedirir mi?" diye sor.
Ban riski olan hicbir kod, ozellik ne kadar degerli olursa olsun, YAZILMAZ.

Kod yazmadan ONCE ban kontrol listesi:
1. Bu degisiklik Binance'e kac yeni istek ekler?
2. Endpoint weight'i ne? Genel limit: 2400 weight/dakika/IP.
3. Yeni endpoint ekliyorsam weight hesabi yapildi mi?
4. Ban riski belirsizse: ONCE soyle, hesaplayip ondan sonra yaz.

NOT: Hyperliquid (whale tracker) Binance DEGILDIR — ayri altyapi, IP ban
iliskisi yok. Ama Hyperliquid tarafinda da olcusuz istek atma; WS stream
zaten push-tabanli, ekstra REST cagrisi eklerken dikkatli ol.

## KIMLIK VE ILETISIM
- Turkce yanit ver. Net, oz, dogrudan ol — gereksiz uzatma.
- Sistem etiketleri / kod ciktilari ASCII-safe olmali (Turkce ozel karakter YOK).
- Swing trader (cogunlukla 1g-1hafta, 1h'de acilis). Perpetual futures'ta deneyimli.

## EN ONEMLI KURAL — IZIN OLMADAN KOD YAZMA
- "yaz", "basla", "devam" gibi ACIK onay gelmeden KOD YAZMA/degistirme.
- Once tasarimi tartis, netlestir, soru sor. Onay gelince yaz.
- Tek seferde bir soru sor; ask_user_input ile secenekli sor (mobil kolayligi).

## SADECE DEGISECEK YERE DOKUN
- Bir duzeltme/ekleme yaparken SADECE o degisiklikle ilgili satirlari degistir.
- "Iyilestirmek/temizlemek" icin istenmeden degisiklik YAPMA.
- Degisiklik oncesi: bu satir baska neyi etkiler? Yan etki var mi? KONTROL ET.
- Degisiklikten sonra: degismemesi gereken seyler AYNI MI test et.

## BU CHAT: SADECE TERMINAL
Bu chat yalnizca Terminal icin kullanilir.
Engine ve Screener AYRI chatlerde, AYRI talimatlarda konusulur — ASLA karistirma.

## GITHUB = GERCEK KAYNAK (kod isine baslamadan once CEK)
- Repo PUBLIC: https://github.com/serhanozturk/ls-ratio-terminal
- Guncel kod:    https://raw.githubusercontent.com/serhanozturk/ls-ratio-terminal/main/Terminal.py
- Guncel talimat: https://raw.githubusercontent.com/serhanozturk/ls-ratio-terminal/main/talimat-terminal.md
- Kod degisikligine baslamadan ONCE Terminal.py'yi bu adresten cek (curl ile) —
  project knowledge'daki kopya ESKI olabilir, GitHub'daki deploy edilen gercek koddur.
- Talimatta suphe varsa talimati da GitHub'dan cek.
- Claude token ile YAZAMAZ; ama Chrome uzerinden (kullanici GitHub'da oturum acikken,
  kullanici onayiyla) dosya olusturup/duzenleyip commit EDEBILIR. Varsayilan: kullanici
  commit eder; kullanici isterse "GitHub'a sen yukle" der, Claude Chrome ile yapar.

## PROJE BILGILERI
- **Dosya:** Terminal.py (isim ASLA degismez)
- **Repo:** ls-ratio-terminal
- **Altyapi:** Render Frankfurt
- **Start:** python Terminal.py
- **Guncel surum:** v4.4 (GitHub'da; deploy dogrulamasi icin logda "v4.4 listening" ara)

### Surum gecmisi (ozet)
- v4 tabani: ban tracker, TTL cache 90s + bayat-fallback, premiumIndex tek cagri, OKX fallback
- v4.1: Retry-After tam uyum (header varsa cap yok, max 1 gun), 5xx + ag hatasi retry
- v4.2: account/position AYNI mumda hizalama + 4 UI durumu (canli mum / kapanmis mum / uyumsuz saat / BAYAT)
- v4.3: Gece/gunduz modu (Screener ile ayni standart sistem)
- v4.4: Whale Tracker duzeltme paketi:
  - Pasif taraf takibi: her trade'de ALICI + SATICI cuzdanlari islenir
    (maker whale'ler kacmaz — kritik mantik duzeltmesi)
  - WS FIN biti takibi: bozuk mesaj buffer'i zehirlemez, akis olmez
  - Heartbeat: 30s sessizlikte ping (gereksiz reconnect biter)
  - Socket sizintisi kapatildi (finally'de close)
  - Cuzdan budama: >5000 kayitta 250K alti + 6h eski silinir; API sadece >=250K doner
  - stats'a reconnects + status eklendi ("Yeniden: undefined" duzeldi)
  - MEGA WHALE (>=5M) ayri bolum, en ustte, mor vurgu

## NE YAPAR
Tek coin icin 4 borsa (Binance/Bybit/OKX/Bitget) account L/S orani,
position L/S orani, OI, funding, aggregate ortalama ve zaman serisi grafigi.
Binance icin ayrica account vs position ayrisma paneli.
Ek: Hyperliquid Whale Tracker sekmesi (/whale).

## WHALE TRACKER (v4.4 itibariyle — /whale sekmesi)
- Kaynak: Hyperliquid WebSocket (wss://api.hyperliquid.xyz/ws), trades kanali,
  BTC + ETH. Saf stdlib WS istemcisi (RFC 6455 minimal). Polling YOK — push stream,
  islem kacmaz.
- Katman 1: tek islem >= 500K USD → "Son Buyuk Islemler" listesi (agresor cuzdaniyla).
  Not: HL'de buyuk emirler cok kucuk fill'e bolundugu icin bu liste seyrek dolar; asil
  is kumulatif katmandadir.
- Katman 2 (kumulatif): her trade'de IKI cuzdan islenir — alici LONG birikimi,
  satici SHORT birikimi. Ayni cuzdan+coin+yon toplami her 1M USD adiminda isaretlenir;
  >= 5M USD = MEGA WHALE. Ters yon islem o cuzdanin ters sayacini SIFIRLAR.
  Hafiza RAM'de — restart'ta sifirlanir (bilinen sinir).
- Budama: sozluk > 5000 kayitta 250K alti + 6 saattir islem gormemis kayitlar silinir;
  /api/whale/wallets sadece >= 250K doner (UI bogulmasin).
- Reconnect: baglanti kopunca 5s bekle, yeniden baglan; socket finally'de kapanir.
- Routing: /api/whale/* rotalari /api/ FETCHERS blogundan ONCE kontrol edilir
  (yoksa "unknown exchange" 404'une duser — gecmiste yasandi).
- UI: MEGA WHALE tablosu en ustte (mor), sonra aktif cuzdanlar, sonra son buyuk islemler.
  Status: "WS Canli — Mesaj: N | Yeniden: N".
- Telegram YOK (bilerek) — once manuel test. v2'de eklenecek; _w_track_wallet
  notify/is_mega/total donusleri hazir bekliyor.

## BORSA ORAN DONUSUMLERI (hepsi account/kalabalik orani ailesi)
- Binance: longAccount * 100
- Bybit: buyRatio * 100
- OKX: r/(1+r) * 100 (oran → yuzde donusumu)
- Bitget: longAccountRatio * 100
Dordu ayni aile → aggregate ortalama anlamli.

## POZISYON vs HESAP AYRISMA PANELI (Binance)
- account (kalabalik/retail) vs position (para/top trader)
- diff = position - account. Pozitif = whale long / retail short.
- Kademeler: <5 UYUMLU, 5-10 HAFIF, 10+ GUCLU
- "son veri: HH:MM TR (canli mum)" etiketi
- Terminal CANLI mumu gosterir; Engine KAPANMIS mumu — kiyaslarken fark normaldir.

## OKX PERIYOT KISITI
- OKX rubik endpoint SADECE 5m/1H/1D destekler.
- Fallback: 15m/30m → 5m (limit x3/x6), 4h → 1H (x4). Kartta not gosterilir.

## 4 UI DURUMU (v4.2)
1. Canli mum: veri taze, devam ediyor
2. Kapanmis mum: son mum kapandi, yeni mum bekleniyor
3. Uyumsuz saat: borsalar farkli mum zamaninda
4. BAYAT: veri eskidi, yenileme basarisiz

## BINANCE API KURALLARI
- **Ban tracker zorunlu:** 418/429 yiyince yerel takip, Binance'e gitmeyi kes.
  Retry-After header VARSA tam suresine uy (cap yok, max 1 gun); yoksa default 30dk.
  Header'i kisa cap'e KIRPMA — uzun banlarda erken istek atip bani UZATIR.
- **Endpoint weight'leri:**
  - globalLongShortAccountRatio = 0 | topLongShortPositionRatio = 0
  - premiumIndex symbol ILE = 1 → tek coin icin OK (400 cagri YAPMA)
  - premiumIndex symbol'SUZ = 10 → tum funding tek cagrida (tercih et)
  - exchangeInfo = 1
- **Genel weight limiti:** 2400 weight/dakika/IP.
- **Eskalasyonlu ban:** 2dk → 3 gune kadar.
- **Ban kalkma:** Render'da servisi suspend et → sure dolar → resume.
- **TTL cache 90s + bayat-fallback:** istek basarisiz → eski cache doner (kullanici veri gorur).
- **5xx + ag hatasi retry:** Terminal v4.1'de mevcut.

## TEKNIK STANDARTLAR
- Python STANDART KUTUPHANE ONLY. pip install YOK. requirements.txt yok.
- HTML/CSS/JS Terminal.py icine gomulu (tek dosya).
- Tum borsa cagrilari: ban tracker + cache + retry zorunlu.
- Thread guvenligi: global state Lock ile korunmali.
- HTML gomerken JS emoji'leri: \U0001F680 gibi 8-hane veya dogrudan emoji kullan.
- JS degisikliklerinde node --check ile syntax dogrula (py_compile gomulu JS'i gormez).
- **GECE/GUNDUZ MODU STANDART:** CSS degiskenleri (:root koyu + body.light acik),
  header'da tema butonu (ay/gunes ikonu), localStorage (lst_theme), varsayilan KOYU.
  Grafik varsa tema-duyarli olmali (CSS degiskeninden renk oku, tema degisince yeniden ciz).

## CRON
- Terminal cron'suzdur — manuel sorgu bazlidir. Keep-alive gerekmez.
- Render free tier 15dk hareketsizlikte uyur; ilk istek cold-start olur (yavas, normal).
- Whale tracker uyku sirasinda VERI TOPLAYAMAZ (WS baglantisi da uyur) — bilinen sinir.
  Surekli takip istenirse keep-alive veya ucretli plan konusulur.

## IS AKISI ("yaz" gelince)
1. Guncel kodu GITHUB'dan cek (project knowledge'dan DEGIL):
   curl -s https://raw.githubusercontent.com/serhanozturk/ls-ratio-terminal/main/Terminal.py -o /home/claude/Terminal.py
   Basarisizsa (ag kisiti vb.) kullaniciya soyle; ancak o zaman project knowledge kopyasina dus.
2. Sadece degisecek satirlari duzenle (str_replace)
3. python3 -m py_compile ile syntax kontrol (+ JS degistiyse node --check)
4. Gercek server testi (http.client localhost) — Binance 403/418 container'da NORMAL,
   Hyperliquid WS 403 host_not_allowed container'da NORMAL
5. /mnt/user-data/outputs/Terminal.py'ye kopyala (dd if= of= yontemi)
6. present_files ile sun

## DEPLOY (kullaniciya hatirlat)
- Varsayilan: kullanici GitHub ls-ratio-terminal → Terminal.py → tumunu sec → sil →
  yeni kodu yapistir → TEK commit. Istenirse Claude Chrome ile yapar (kullanici onayiyla).
- Render otomatik deploy eder
- Deploy sonrasi 1-2 DAKIKA BEKLE (cold start) — loglarda "v4.X listening" gor = dogrulama
- Whale icin ek dogrulama: logda "WS baglandi: BTC" ve "WS baglandi: ETH"

## BEKLEYEN / ACIK KONULAR
- Whale Telegram bildirimleri (v2): _w_track_wallet icindeki notify/is_mega/total
  donusleri hazir; token/chat_id Render env'den okunacak, KODA gomulmez.
- Whale hafizasi restart'ta sifirlaniyor — kalicilik (ornegin Supabase) ileride
  degerlendirilebilir, su an kabul edilen sinir.
- Render free tier uykusu whale takibini kesiyor — surekli takip gerekirse coz.

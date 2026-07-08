# TEFAS Fon Analiz Sistemi — v2

Türkiye Elektronik Fon Alım Satım Platformu (TEFAS) verilerini analiz eden
kantitatif finansal analiz aracı. Bu, [`Tefas_New`](../Tefas_New) projesinin
**aynı mimariyle ama temiz, test edilmiş ve hızlı** şekilde yeniden inşa edilmiş
sürümüdür.

> Aynı mimari, daha iyi mühendislik **ve düzeltilmiş finansal metodoloji**: v2,
> v1'in mimarisini (ETL→metrik→skor→rapor) korur ama uzman değerlendirmesiyle
> saptanan hataları giderir — bu nedenle **v1 ile birebir aynı çıktıyı artık
> ÜRETMEZ** (bkz. aşağıda "Metodoloji düzeltmeleri"). ~3.5× daha hızlı çalışır ve
> her formül **birim testleriyle** korunur.

## Hızlı başlangıç

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # POSIX: .venv/bin/python
.venv/Scripts/python -m tefas run --fund-type YAT --risk-free-rate 45
```

Çıktı: `Reports/tefas_premium_rapor_yatirim.pdf` + `Output/*.csv` / `*.parquet`.

Test:

```bash
.venv/Scripts/python -m pytest -q        # 34 passed
```

## Tek komut, tek CLI

```bash
tefas run     --fund-type YAT --risk-free-rate 45   # tüm pipeline (bellekte)
tefas compare --fund-type YAT --risk-free-rate 45   # belirli fonları karşılaştır
tefas etl     --fund-type YAT                        # yalnızca ETL  -> combined.parquet
tefas metrics --fund-type YAT --risk-free-rate 45   # combined.parquet'ten
tefas score   --fund-type YAT --risk-free-rate 45   # metrics+combined parquet'ten
tefas report  --fund-type YAT --risk-free-rate 45   # skorlu+metrik parquet'ten
tefas holdings show|returns|check                    # kişisel portföy takibi (aşağıda)
tefas dashboard                                      # interaktif web paneli (aşağıda)
```

`run` için ek bayraklar: `--filter`, `--exclude`, `--no-active-only`,
`--keep-suspect`, `--min-aum`, `--min-fund-age`, `--no-report`.

## Kişisel portföy takibi (`tefas holdings`)

Gerçek işlemlerini kök dizindeki `portfolio_transactions.csv`'ye gir (şablon:
`portfolio_transactions.example.csv`; dosya gitignore'dadır — kişisel veridir):

```csv
Tarih,Fon Kodu,Islem,Adet,Fiyat,Not
2025-03-10,PRY,ALIS,1250.5,4.8210,ilk alım
2025-06-02,PRY,SATIS,400,5.9105,
```

```bash
tefas holdings show     # FIFO pozisyonlar, maliyet, açık/realize K-Z, ağırlıklar
tefas holdings returns  # XIRR (para-ağırlıklı, manşet) + TWR (fon kıyası için)
tefas holdings check    # model portföy sapması, kendi kendini finanse eden
                        # rebalans önerileri, kovaryans risk özeti, skor sinyalleri
```

Sinyaller (`check`), her `tefas run`'da `Output/score_history_*.parquet`'e
birikir: skor persentili ~30 günde ≥10 puan düşen ya da üst çeyrekten çıkan
pozisyonlar işaretlenir (2+ tarih birikince aktifleşir).

## İnteraktif web paneli (`tefas dashboard`)

```bash
.venv/Scripts/python -m pip install -e ".[dashboard]"   # streamlit + plotly (bir kez)
tefas dashboard                                          # http://localhost:8501
```

Sayfalar: **Genel Bakış** (KPI + ilk 10), **Fon Keşif** (tema/skor/AUM
filtreleri + risk-getiri haritası), **Fon Detay** (büyüme, drawdown, yuvarlanan
metrikler — PDF ile aynı `charts.prep_*` verisi), **Portföyüm** (işlem defteri
editörü, K/Z, XIRR/TWR, değer grafiği), **Denge & Sinyal** (model sapması,
rebalans, risk katkıları, sinyaller). Panel yalnızca `Output/*.parquet` okur;
pipeline'dan tamamen bağımsızdır ve CLI ile aynı işlem defterini kullanır.

## Veri güncelleme (GetDataSet)

Analiz, `Dataset/` altındaki CSV'lere ve `platform_status` JSON'una dayanır.
Bunları tazelemek için `GetDataSet/` içindeki bağımsız scriptler kullanılır:

```bash
# Fiyat/AUM verisi — TEFAS API'dan eksik ayları indir (saf stdlib)
python GetDataSet/download_tefas.py --fund-type YAT --update

# Platform durumu (aktif/pasif) — cloudscraper gerektirir
.venv/Scripts/python -m pip install -e ".[fetch]"   # veya: pip install cloudscraper
python GetDataSet/fetch_platform_status.py --fund-type YAT --update
```

> Not: Scriptler sabit TEFAS `TOKEN`/`DEVICE_ID` kullanır; HTTP 401/403 veya WAF
> hatası alırsan tarayıcıdan güncel token/cookie alıp script başındaki sabitleri
> yenilemen gerekir.

## İnteraktif mod ve config dosyası

Hiç argüman vermeden çalıştırırsan soru-cevap sihirbazı açılır (fon tipi,
risksiz faiz, include/exclude, vb.):

```bash
python -m tefas        # veya kurulu ise: tefas
```

Sihirbazın ilk adımında ayarları **adım adım** girebilir ya da bir **config
dosyasından** yükleyebilirsin. Adım adım modun sonunda ayarları dosyaya
**kaydetmeyi** önerir. Varsayılan config yolu proje kökünde
`tefas.config.json`'dur (Enter'a basınca bu kullanılır).

Komut satırından da:

```bash
tefas run --config                       # varsayılan tefas.config.json'dan yükle
tefas run --config baska.json            # belirli dosyadan yükle
tefas run --fund-type EMK --save-config  # etkin ayarları tefas.config.json'a kaydet
tefas run --config baska.json --fund-type EMK   # CLI config'i ezer
```

Config JSON veya TOML olabilir; desteklenen anahtarlar: `fund_type`,
`risk_free_rate`, `include`, `exclude`, `active_only`, `keep_suspect`,
`min_aum`, `min_fund_age`, `write_report` ve **makro oranlar**:
`inflation_rate`, `policy_rate`, `management_fee_rate`. Makro oranlar artık
kodda sabit değildir; `tefas.config.json`'dan okunur, eksikse koddaki
varsayılana düşülür ve raporun kapağında "(varsayılan)" olarak işaretlenir. Örnek:
[`tefas.config.example.json`](tefas.config.example.json). **Öncelik:** CLI
argümanı > config dosyası > yerleşik varsayılan.

### Filtre dosyası (`.txt`)

Yalnızca include/exclude için sade bir düz-metin formatı da desteklenir
([`filter_config.txt`](filter_config.txt)). `[INCLUDE]` / `[EXCLUDE]` bölümleri,
satır başına bir kelime; boş satırlar ve `#` ile başlayanlar yok sayılır:

```
[INCLUDE]
# PARA PİYASASI      <- # kaldırınca aktifleşir
[EXCLUDE]
ALTIN
GÜMÜŞ
PARA PİYASASI
```

Kullanımı (uzantısı `.txt` olduğundan filtre dosyası olarak ayrıştırılır):

```bash
tefas run --config filter_config.txt --fund-type YAT
```

İnteraktif modda da "Filtreler nasıl belirlensin?" adımında **dosyadan yükle**
seçeneği bu dosyayı kullanır (Enter = `filter_config.txt`).

## Karşılaştırma modu (`tefas compare`)

Belirli fonları **yan yana** kıyaslayan ayrı bir PDF üretir — tarama/skorlama
değil, senin seçtiğin kodların doğrudan karşılaştırması. Kodları
[`comparison_config.txt`](comparison_config.txt) dosyasına (satır başına bir kod,
`#` yorum, isteğe bağlı `[COMPARE]` başlığı) yaz ya da komut satırından ver:

```bash
tefas compare --fund-type YAT --risk-free-rate 45          # comparison_config.txt'ten
tefas compare --codes PRY,PBR,BMU                          # dosya yerine kodlar
tefas compare --config baska_liste.txt                     # başka dosya
```

Çıktı: `Reports/tefas_karsilastirma_yatirim.pdf`. İçerik:

- **Özet & öne çıkanlar:** her ölçütte (getiri, Sharpe, düşük vol, drawdown, reel
  getiri, likidite, tutarlılık) en iyi fonu gösteren tablo + **radar** grafiği.
- **Karşılaştırma tablosu:** metrikler satır, fonlar sütun; her satırın en iyi
  hücresi **yeşil** vurgulanır.
- **Getiri & büyüme:** ortak dönemde normalize (100 taban) büyüme + dönemsel
  (1A/3A/6A/1Y) getiri barları.
- **Risk & dayanıklılık:** risk-getiri konumu + fonların **sualtı/drawdown**
  eğrileri.
- **Korelasyon:** fonların birlikte hareketi (çeşitlendirme için).

Kodlar **"olduğu gibi"** kıyaslanır: aktiflik/rf/AUM/yaş filtresi uygulanmaz;
yalnızca verisi kullanılamayacak kadar az (< 20 gözlem) olan fon atlanır.
İnteraktif modda "Fon karşılaştırma" seçeneğiyle de erişilir.

## Mimari

Bilinçli olarak v1 ile **aynı aşamalı yapı** (ETL → metrik → skor → rapor) —
çünkü bu doğru ayrıştırma. Değişen, *nasıl bağlandıkları*:

```
tefas/
  config.py        Tek merkezde tüm sabitler + yollar (paths_for(fund_type))
  io_utils.py      Encoding'i bir kez ayarla; Türkçe sayı/CSV oku
  etl.py           load_combined() -> DataFrame  (dosyaya yazmaz)
  data_quality.py  Saf fonksiyonlar: bozuk seri tespiti, winsorize
  metrics.py       Saf metrik fonksiyonları + compute_metrics()
  themes.py        Tema sınıflandırması + akran (tema medyanı) istatistikleri
  scoring.py       Percentile-rank composite skor, shrinkage, risk profilleri
  report.py        generate(scored_df, metrics_df, ...) -> PDF
  pipeline.py      run(): aşamaları BELLEKTE bağlar, parquet önbellek
  cli.py           Tek `tefas` komutu, alt-komutlar
tests/             56 altın-değer + entegrasyon/smoke testi
```

## v1 incelemesinden uygulanan bulgular

Bu sürüm, v1 üzerine yapılan değerlendirmedeki her maddeyi uygular:

| # | Bulgu | v1 | v2 |
|---|-------|----|----|
| 1 | **Orkestrasyon** | `run_analysis.py` her aşamayı ayrı `subprocess` başlatır, aşamalar ~37 MB CSV'yi **3 kez** okur/yazar | `pipeline.run()` aşamaları fonksiyon olarak çağırır, DataFrame'ler bellekte aktarılır → **~3.5× hız** |
| 2 | **Ara format** | Ara veri CSV (37.6 MB, tipsiz, yavaş) | **Parquet** (8.7 MB, tipli) — **4.3× küçük**; insan-dostu özetler ayrıca CSV |
| 3 | **Testler** | Yok — finansal formüller satır-içi gömülü | Her formül **saf fonksiyon** + **34 test** (altın değerler) |
| 4 | **CLI** | ~8 script, her birinde ayrı argparse | Tek `tefas` komutu, paylaşılan config |
| 5 | **Ölü kod** | Legacy raporlar, scipy-bağımlı optimizer/stress/black-litterman/factor/monte-carlo, çalışmayan Flask dashboard | Yalnızca raporun kullandığı yollar — hepsi temizlendi |
| 6 | **Encoding** | UTF-8 düzeltmesi her script'te tekrar | `io_utils.setup_utf8()` tek yerde |

**Not (CSV büyümesi):** v1'deki "combined CSV 17 MB → 37 MB" gözlemi bir hata
*değildi* — ETL eski çıktıyı silip `(Fon Kodu, Tarih)` üzerinde dedup ile temiz
yeniden inşa ediyor; büyüme yalnızca veri setine eklenen yeni aylardandı. Aynı
dedup mantığı v2'de korundu.

## Yatırım danışmanlığı için içerik iyileştirmeleri

Görsel kalite zaten yeterliydi; eklenenler **analitik içerik** (kozmetik değil):

- **Veri kapsamı uyarısı (#1):** 1 yıldan (252 iş günü) kısa fiyat geçmişi olan
  fonlar tablolarda **`*`** ile işaretlenir; yönetici özetinde kaç fonun ince
  geçmişe sahip olduğu ve medyan gözlem belirtilir. Kısa seride 1Y getiri/Sharpe
  gürültülüdür — artık şeffaf.
- **Benchmark karşılaştırması (#2):** Yönetici özetinde fonların enflasyonu
  (%55), politika faizini (%50) geçme oranı, pozitif reel getiri oranı ve
  ortalama reel getiri. (Örn. mevduatı geçen 490 fonun yalnızca ~%45'i
  enflasyonu da geçiyor; ortalama reel getiri **negatif** — danışmanlık için
  kritik bir gerçek.)
- **Kovaryans-temelli portföy riski (#4):** Örnek portföyün volatilitesi artık
  fonların gerçek günlük getiri **kovaryansından** (σ = √(wᵀΣw)) hesaplanır;
  çeşitlendirme-yok ağırlıklı ortalama vol ve **çeşitlendirme kazancı** ile
  ortalama ikili korelasyon raporlanır. v1'deki sezgisel "bant" kaldırıldı; bu
  matematik [tests/test_portfolio.py](tests/test_portfolio.py) ile doğrulanır.

Hâlâ açık (danışmanlık için ileride): fon-bazlı gerçek gider oranı (TER) ve
işlem maliyetleri; ileriye dönük senaryo/Monte-Carlo. Bunlar ek veri kaynağı
gerektirir.

## Bilinçli olarak yapılmayanlar

Web servisi, veritabanı, async/DAG orkestrasyonu, eklenti mimarisi — *yok*. Veri
~500 fon için aylık CSV; doğru ölçek, parquet önbellekli tek bir Python paketi +
CLI. Daha ağırı gereksiz karmaşıklık olurdu.

## Metodoloji (özet)

Formüller [tests/](tests/) ile altın-değerlere karşı doğrulanır:

- **Ortak değerlendirme penceresi:** Volatilite, Sharpe, Sortino, Calmar,
  drawdown ve VaR tüm fonlarda **ortak gerilemeli ~1 işlem yılı** penceresinde
  (`config.SCORING_LOOKBACK_DAYS`) hesaplanır; farklı geçmiş uzunluğundaki
  fonlar aynı dönem üzerinden kıyaslanır. Kuruluştan-bugüne değerler künye
  kartlarında referans olarak kalır.
- **Gösterilen/skorlanan getiri yıllıklandırılmıştır:** tablolar ve skorlama
  "Yıllık Getiri"yi (pencere içi CAGR) kullanır — Sharpe/Sortino ile aynı baz.
  1 yıldan kısa geçmişli (`*`) fonlarda bu, daha kısa bir pencereden
  yıllıklandırıldığı için daha gürültülüdür (ör. 8 aylık %64 kümülatif ≈ %110
  yıllık). Ham kümülatif dönem getirisi ayrıca `Getiri_1Y` sütununda saklanır.
- **CAGR** gerçek uç fiyatlardan; **Volatilite/Sortino** winsorize (±%25) günlük
  getirilerle; **Sharpe** = (Getiri − Rf)/Vol; **Calmar** = (Getiri − Rf)/MaxDD.
- **Composite skor** = yüzdelik-sıra ağırlıklı (Sharpe %25, Sortino %15, düşük
  drawdown %20, yıllık getiri %20, **tema-içi getiri %5**, tutarlılık %7,5,
  likidite %7,5) — outlier'a dayanıklı; getiri etkisi toplamda %25 (%20 mutlak +
  %5 akran-göreli). Tutarlılık pozitif gün/ay oranına dayanır; drawdown/Sortino'yu
  tekrar kullanmaz (çifte sayım yok).
- **Kısa geçmiş düzeltmesi (shrinkage):** skorlamadaki getiri, güvenilirlik
  ağırlığı `w = pencere_günü / 189` (en çok 1) ile akran (tema ≥ 5 fon, yoksa
  evren) medyanına çekilir (`Yillik_Getiri_Duzeltilmis`). 189+ gün geçmişte
  düzeltme sıfırdır; tablolarda gösterilen getiriler ham kalır.
- **Akran (tema) kıyası:** harici endeks yoktur; benchmark veri-seti içidir.
  `Tema_Rel_Skor` fonun kendi temasındaki getiri yüzdeliğidir (tema < 5 fon ise
  NaN); büyüme grafiklerinde evren/tema medyan patikası kesikli gri çizgidir.
- **Sıralama vs. seçim:** skorlar tüm (veri-kalitesi geçerli) evren üzerinden;
  AUM/yaş bir **uygunluk** filtresidir (satır düşürmez). **rf artık eleme
  kriteri değildir** — `Rf_Ustu` bilgilendirici bayrağı ve tablolardaki `rf+`
  sütunu olarak raporlanır. Öneriler yalnızca uygun fonlardan gelir.
- **Veri kalitesi:** tek günde > %35 hareket eden fonlar elenir.

> **Not (v2.1):** Composite ağırlıklar yeniden dengelendi (getiri %25 → %20 + %5
> tema-içi; shrinkage eklendi) — sıralamalar v2.0'a göre kayabilir. Kayma
> beklenen yerler: kısa geçmişli fonlar (medyana çekilir) ve tema-içi geride
> kalanlar; uzun geçmişli güçlü fonlar en fazla 1-2 sıra oynar.

### Metodoloji düzeltmeleri (v1 → v2 paritesini bilinçli kırar)

1. **Ortak pencere:** risk metrikleri artık her fonun *tüm geçmişi* yerine ortak
   gerilemeli 1 yılda hesaplanır (elma-armut sıralaması giderildi).
2. **Sıralama/seçim ayrımı:** rf filtresi artık sıralamadan önce evreni budamaz;
   v2.1'den itibaren uygunluk kriteri de değildir — yalnızca bilgilendirici
   `Rf_Ustu` bayrağıdır (yüksek rf değerlerinde evrenin çökmesini önler:
   rf=%65'te 766 fondan yalnızca 66'sı rf üzeri getiri sağlıyordu).
3. **Geçersiz stopaj kaldırıldı:** `net_return`'ün "enflasyon+5 üstüne %15" vergi
   sezgiseli (yıllıklandırılmış orana vergi — boyutsal hata) kaldırıldı;
   `Net_Getiri_1Y` yalnızca yönetim ücreti düşülmüş getiridir.
4. **Çifte sayım giderildi:** Consistency artık drawdown/Sortino/çarpıklığı
   tekrar kullanmaz.

### Rapor (PDF) — yeni içerik

Gösterge paneli (KPI kartları + dağılım histogramları + benchmark barları),
fon künye kartları (tear-sheet: metrik ızgarası + büyüme/drawdown sparkline),
portföy **risk katkısı** (kovaryanstan) ve **sualtı/drawdown** grafiği, tail-risk
(VaR/CVaR) tablosu ve kategori/tema kırılımı eklendi.

v2.1 eklemeleri:

- **Aylık getiri takvimi:** ilk 10 fonun ay-ay getiri ısı haritası + evren
  medyan satırı (0 merkezli ıraksak palet; fonun olmadığı aylar gri).
- **Yuvarlanan 63 günlük getiri & volatilite:** performansın döneme yayılıp
  yayılmadığını ve risk rejimi değişimlerini gösterir (rf referans çizgisiyle).
- **Fon detay sayfaları:** ilk 6 öneri için tam sayfa — büyüme + tema medyanı
  kıyası, sualtı eğrisi, aylık getiri barları ve `Fon | Tema Medyanı | Evren
  Medyanı` akran tablosu + tema-içi yüzdelik.
- **Tutarlı fon renkleri:** bir fon tüm grafiklerde aynı rengi taşır; palet
  renk-körlüğü/kontrast kontrollerinden geçirildi.
- **ORTA (Moderate) profili** risk-profili bölümüne eklendi (portföy kurulumu
  zaten kullanıyordu); büyüme grafiğine **evren medyanı** benchmark çizgisi
  eklendi; kapaktaki makro oranlar config'ten gelir.

**Uyarı:** Bu araç yatırım tavsiyesi vermez. Geçmiş performans gelecek getiriyi
garanti etmez.

## Güncel öneri akışı

Bu sürümde ürün hedefi, yalnızca "en yüksek skorlu fon" listesi değil,
**açıklanabilir, risk profiline uygun fon öneri sistemi**dir.

- **Skorlama:** `tefas/scoring.py` ham metrikleri composite ve profil skorlarına
  çevirir. Ağırlıklar ve model sürümü `tefas/model_config.py` altında
  versiyonlanır; skor çıktısında `Model_Version` kolonu bulunur.
- **Karar katmanı:** `tefas/allocation.py` skordan ayrı olarak uygunluk filtresi,
  profil bazlı sıralama, portföy seçim kuralları ve karar bayraklarını üretir.
  AUM bir getiri skoru değil, likidite/uygunluk sinyalidir.
- **Genç fonlar:** 1 yıldan kısa fiyat geçmişli fonlar ana öneriye girmez;
  izleme listesi adayı olarak etiketlenir.
- **Risk/free-rate yorumu:** rf altındaki düşük oynaklıklı fonlar
  "düşük oynaklık ama rf altı" bayrağıyla görünür hale gelir.

## Validasyon, PDF ve Dashboard

- **Walk-forward validasyon:** `Output/backtest_walkforward_*.csv` varsa PDF ve
  dashboard aynı `tefas/validation.py` özetini kullanır: kat sayısı, 1A/3A/6A
  sonuçları, ortalama fark, medyan fark, hit-rate ve varsa turnover.
- **Backtest yoksa:** rapor ve dashboard bunu sessiz geçmez; "validasyon dosyası
  bulunamadı" uyarısı verir.
- **PDF karar raporu:** akış karar özeti, önerilen portföy, uyarı bayrakları,
  model doğrulama, risk katkısı ve fon detayları etrafında düzenlenmiştir. Risk
  katkısı ve korelasyon grafikleri okunabilir ayrı sayfalarda tutulur.
- **Dashboard:** mevcut sayfalar korunur; `Karar Merkezi` sayfası portföy
  önerisi, model doğrulama ve risk merkezi sekmelerini sunar.

## Kapsam dışı veri entegrasyonu

Bu çalışma yeni KAP/EVDS/harici veri entegrasyonu eklemez. Dashboard ve raporlar
yalnızca mevcut `Dataset/`, `Output/*.parquet`, mevcut benchmark klasörü ve
varsa mevcut backtest CSV çıktılarını kullanır.

# TEFAS Fon Analiz Sistemi — v2

Türkiye Elektronik Fon Alım Satım Platformu (TEFAS) verilerini analiz eden
kantitatif finansal analiz aracı. Bu, [`Tefas_New`](../Tefas_New) projesinin
**aynı mimariyle ama temiz, test edilmiş ve hızlı** şekilde yeniden inşa edilmiş
sürümüdür.

> Aynı sonuçlar, daha iyi mühendislik: v1 ile **birebir aynı çıktıyı** üretir
> (490 fon; Ort. getiri %64.5, Sharpe 1.18, composite 50.1; aynı ilk-5: PSE,
> PRU, PBR, PRY, KKL) — ama **~3.5× daha hızlı** (29.7 sn vs 1 dk 44 sn) ve
> **20 birim testi** ile korunan finansal matematik.

## Hızlı başlangıç

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # POSIX: .venv/bin/python
.venv/Scripts/python -m tefas run --fund-type YAT --risk-free-rate 45
```

Çıktı: `Reports/tefas_premium_rapor_yatirim.pdf` + `Output/*.csv` / `*.parquet`.

Test:

```bash
.venv/Scripts/python -m pytest -q        # 20 passed
```

## Tek komut, tek CLI

```bash
tefas run     --fund-type YAT --risk-free-rate 45   # tüm pipeline (bellekte)
tefas etl     --fund-type YAT                        # yalnızca ETL  -> combined.parquet
tefas metrics --fund-type YAT --risk-free-rate 45   # combined.parquet'ten
tefas score   --fund-type YAT --risk-free-rate 45   # metrics+combined parquet'ten
tefas report  --fund-type YAT --risk-free-rate 45   # skorlu+metrik parquet'ten
```

`run` için ek bayraklar: `--filter`, `--exclude`, `--no-active-only`,
`--keep-suspect`, `--min-aum`, `--min-fund-age`, `--no-report`.

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
`min_aum`, `min_fund_age`, `write_report`. Örnek:
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
  scoring.py       Percentile-rank composite skor, risk profilleri
  report.py        generate(scored_df, metrics_df, ...) -> PDF
  pipeline.py      run(): aşamaları BELLEKTE bağlar, parquet önbellek
  cli.py           Tek `tefas` komutu, alt-komutlar
tests/             20 altın-değer + entegrasyon testi
```

## v1 incelemesinden uygulanan bulgular

Bu sürüm, v1 üzerine yapılan değerlendirmedeki her maddeyi uygular:

| # | Bulgu | v1 | v2 |
|---|-------|----|----|
| 1 | **Orkestrasyon** | `run_analysis.py` her aşamayı ayrı `subprocess` başlatır, aşamalar ~37 MB CSV'yi **3 kez** okur/yazar | `pipeline.run()` aşamaları fonksiyon olarak çağırır, DataFrame'ler bellekte aktarılır → **~3.5× hız** |
| 2 | **Ara format** | Ara veri CSV (37.6 MB, tipsiz, yavaş) | **Parquet** (8.7 MB, tipli) — **4.3× küçük**; insan-dostu özetler ayrıca CSV |
| 3 | **Testler** | Yok — finansal formüller satır-içi gömülü | Her formül **saf fonksiyon** + **20 test** (altın değerler) |
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

Finansal formüller v1 ile birebir aynıdır ve artık [tests/](tests/) ile
doğrulanır:

- **CAGR** gerçek uç fiyatlardan (aritmetik ortalama bileşiklemesinin aşırı
  tahminini önler).
- **Volatilite / Sortino** winsorize edilmiş (±%25) günlük getirilerle.
- **Sharpe** = (Getiri − Rf) / Volatilite; **Calmar** = (Getiri − Rf) / MaxDD.
- **Composite skor** = yüzdelik-sıra ağırlıklı (Sharpe %30, Sortino %20, düşük
  drawdown %20, getiri %20, tutarlılık %5, likidite %5) — outlier'a dayanıklı.
- **Veri kalitesi**: tek günde > %35 hareket eden fonlar elenir.

**Uyarı:** Bu araç yatırım tavsiyesi vermez. Geçmiş performans gelecek getiriyi
garanti etmez.

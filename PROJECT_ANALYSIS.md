# TEFAS Fon Analiz Sistemi — Proje Analizi

> **Versiyon:** 2.0.0 | **Dil:** Python 3.10+ | **Platform:** TEFAS (Turkiye Elektronik Fon Alim Satim)

---

## 1. Proje Ozeti

TEFAS Fon Analiz Sistemi, Turkiye'deki yatirim ve emeklilik fonlarinin kantitatif finansal analizini yapan bir aractir. Tefas_New projesinin **ayni mimariyle ama temiz, test edilmis ve hizli** sekilde yeniden insa edilmis surumudur.

### Temel Ozellikler
- **ETL -> Metrik -> Skor -> Rapor** asamali pipeline mimarisi
- **Tek CLI komutu** ile tum analiz (	efas run)
- **Kisisel portfoy takibi** (FIFO, XIRR, TWR getiri)
- **Interaktif web paneli** (Streamlit dashboard)
- **Walk-forward dogrulama** (out-of-sample backtest)
- **PDF rapor** (tear sheet, grafikler, benchmark karsilastirmasi)

---

## 2. Dizin Yapisi

`
Tefas_New2/
+-- tefas/                    # Ana paket (18 modul)
|   +-- __init__.py           # Versiyon: 2.0.0
|   +-- __main__.py           # python -m tefas destegi
|   +-- cli.py                # Tek CLI girisi, alt-komutlar
|   +-- config.py             # Merkezi konfigurasyon (yollar, sabitler)
|   +-- io_utils.py           # UTF-8, Turkce sayi/CSV okuma
|   +-- etl.py                # CSV -> birlesik DataFrame
|   +-- data_quality.py       # Fiyat serisi kalite kontrolu
|   +-- metrics.py            # Saf metrik fonksiyonlari
|   +-- themes.py             # Fon tema siniflandirmasi
|   +-- scoring.py            # Percentile-rank composite skor
|   +-- portfolio.py          # Kovaryans-temelli portfoy riski
|   +-- allocation.py         # Portfoy kurulumu ve rebalans
|   +-- holdings.py           # Kisisel portfoy takibi
|   +-- benchmarks.py         # Benchmark verisi ve goreli metrikler
|   +-- backtest.py           # Walk-forward dogrulama
|   +-- report.py             # PDF rapor uretimi (ReportLab)
|   +-- charts.py             # Grafik uretimi (matplotlib)
|   +-- pipeline.py           # In-process orkestrasyon
|   +-- dashboard/            # Streamlit web paneli
+-- tests/                    # 15 test dosyasi (56+ test)
+-- GetDataSet/               # Bagimsiz veri indirme scriptleri
+-- Dataset/                  # Ham veri (CSV)
+-- Output/                   # Ara ve son ciktilar (parquet + CSV)
+-- Reports/                  # PDF raporlar
+-- pyproject.toml            # Paket tanimi ve bagimliliklar
+-- tefas.config.json         # Calistirma ayarlari
+-- filter_config.txt         # Include/exclude filtreleri
+-- comparison_config.txt     # Karsilastirma fon kodlari
+-- portfolio_transactions.csv # Kisisel islem defteri
`

---

## 3. Mimari ve Veri Akisi

### 3.1 Pipeline Asamalari

`
[ETL] ---> [Metrikler] ---> [Skorlama] ---> [Rapor]
etl.py     metrics.py      scoring.py      report.py
  |            |               |               |
  v            v               v               v
combined    metrics        scored           report.pdf
.parquet    .parquet       .parquet
`

### 3.2 In-Process Orkestrasyon

v1'de her asama ayri subprocess olarak calisiyordu ve ~37 MB CSV 3 kez okunuyordu. v2'de:
- pipeline.run() asamalari fonksiyon olarak cagirilir
- DataFrame'ler bellekte aktarilir
- Ara ciktilar **parquet** olarak onbellege alinir (8.7 MB vs 37.6 MB CSV — **4.3x kucuk**)
- **~3.5x hiz** artisi

### 3.3 Config Onceligi

`
CLI argumani > Config dosyasi > Yerlesik varsayilanlar
`

---

## 4. Modul Detaylari

### 4.1 config.py — Merkezi Konfigurasyon

| Sabit | Deger | Aciklama |
|-------|-------|----------|
| SCORING_LOOKBACK_DAYS | 252 | Skorlama penceresi (~1 islem yili) |
| RETURN_FULL_CREDIT_DAYS | 189 | Shrinkage tam guvenilirlik esigi |
| THEME_MIN_FUNDS | 5 | Tema akrani icin asgari fon |
| DATA_QUALITY_MAX_DAILY_MOVE | 35% | Tek gunluk hareket siniri |
| DAILY_RETURN_CLIP | 25% | Winsorize banti |
| MIN_DATA_POINTS | 20 | Asgari gozlem sayisi |
| TRADING_DAYS_PER_YEAR | 252 | Islem gunu/yil |

**Makro oranlar** (tefas.config.json'dan okunur):
- risk_free_rate (varsayilan: %45)
- inflation_rate (varsayilan: %55)
- policy_rate (varsayilan: %50)
- management_fee_rate (varsayilan: %1)

### 4.2 metrics.py — Saf Metrik Fonksiyonlari

Her formul **bagimsiz test edilebilir** saf fonksiyondur:

| Fonksiyon | Formul | Not |
|-----------|--------|-----|
| annualized_volatility | std * sqrt(252) | ddof=1, winsorize edilmis getirilerle |
| cagr | (P1/P0)^(252/n) - 1 | Gercek uclu fiyatlardan, min 63 gun |
| max_drawdown | Tepe-dip dususu | Pozitif yuzde |
| sharpe_ratio | (R - Rf) / sigma | Yillik bazda |
| sortino_ratio | (R - Rf) / sigma_downside | Geometrik gunluk rf esigi |
| calmar_ratio | (R - Rf) / MaxDD | +-100 ile sinirli |
| historical_var_cvar | Tarihsel percentil | Gunluk ufuk, ham getirilerle |
| period_return | Takvim-bazli | TEFAS uyumlu |
| after_fee_return | Gross - Fee | Yalnizca yonetim ucreti |
| real_return | Fisher denklemi | Enflasyondan arindirilmis |

**Ortak Pencere:** Risk metrikleri (volatilite, Sharpe, Sortino, Calmar, drawdown, VaR) tum fonlarda **son 252 gozlem** uzerinden hesaplanir — farkli gecmis uzunluklarindaki fonlar ayni donemde kiyaslanir.

### 4.3 scoring.py — Composite Skor

**Agirliklar:**
| Bilesen | Agirlik |
|---------|---------|
| Sharpe (percentile) | %25 |
| Dusuk Drawdown (percentile) | %20 |
| Yillik Getiri (shrinkage-duzeltilmis) | %20 |
| Sortino (percentile) | %15 |
| Consistency (pozitif gun/ay) | %7.5 |
| Likidite (AUM) | %7.5 |
| Tema-ici getiri yuzdeligi | %5 |

**Shrinkage:** Kisa gecmisli fonlarin getirisi guvenilirlik agirligiyla (w = gun/189) tema medyanina cekilir. 189+ gun gecmiste duzeltme sirfirdir.

**Risk Profilleri:**
- **Conservative:** Dusuk vol (%40) + dusuk drawdown (%30) + pozitif gun (%15) + tutarlilik (%15)
- **Balanced:** Sortino (%30) + Calmar (%25) + vol bani (%20) + getiri (%15) + tutarlilik (%10)
- **Moderate:** Sharpe (%40) + getiri (%25) + vol bani (%20) + tutarlilik (%15)
- **Aggressive:** Getiri (%40) + momentum (%25) + yuksek vol (%15) + Calmar (%10)

### 4.4 portfolio.py — Portfoy Riski

- **Kovaryans-temelli:** sigma_p = sqrt(wT * Sigma * w) — gercek gunluk getiri kovaryansi
- **Pairwise + shrinkage:** Her fon cifti kendi ortak gozlemini kullanir, sabit-korelasyon hedefine buzulur
- **Risk katkilari:** RC_i = w_i * (Sigma*w)_i / (wT*Sigma*w) — her fonun varyansa yuzde katkisi
- **Cesitlendirme kazanci:** Agirlikli ortalama vol — portfoy vol

### 4.5 holdings.py — Kisisel Portfoy

- **FIFO lot eslemesi:** Her ayris ayri lot olarak takip edilir, satislarda ilk giren ilk cikar
- **XIRR:** Bisection ile duzensiz nakit akislarinin ic verim orani (scipy bagimliligi yok)
- **TWR:** Gunluk zincirlenmis zaman-agirlikli getiri (fon/benchmark kiyasi icin)
- **Sinyaller:** Skor persentili ~30 gunde >=10 puan dusen veya ust ceyrekten cikan fonlar

### 4.6 backtest.py — Walk-Forward Dogrulama

Her ay sonunda:
1. Yalnizca o ana kadarki veriyle metrik + skor hesaplanir (look-ahead yok)
2. Model portfoy kurulur
3. 1 ve 3 aylik ileri getiri olculur
4. Esit-agirlik evren ortalamasi ile karsilastirilir

Ciktilar: Kat basina fark, isabet orani, ortalama fark, portfoy devri (turnover).

---

## 5. CLI Komutlari

`
# Ana pipeline
tefas run --fund-type YAT --risk-free-rate 45

# Bireysel asamalar
tefas etl --fund-type YAT
tefas metrics --fund-type YAT --risk-free-rate 45
tefas score --fund-type YAT --risk-free-rate 45
tefas report --fund-type YAT --risk-free-rate 45

# Karsilastirma
tefas compare --fund-type YAT --risk-free-rate 45
tefas compare --codes PRY,PBR,BMU

# Portfoy takibi
tefas holdings show
tefas holdings returns
tefas holdings check

# Backtest
tefas backtest --fund-type YAT --risk-free-rate 45 --horizons 1 3

# Dashboard
tefas dashboard

# Interaktif mod (sihirbaz)
python -m tefas
`

**Ek bayraklar:** --filter, --exclude, --no-active-only, --keep-suspect, --min-aum, --min-fund-age, --no-report, --config, --save-config

---

## 6. Veri Seti

### 6.1 Ham Veri (Dataset/)
- **Yatirim fonlari:** Dataset/Yatirim/YYYY-MM_DD_YYYY-MM.csv (aylik parcalar)
- **Emeklilik fonlari:** Dataset/Emeklilik/ (ayni format)
- **Benchmark serileri:** Dataset/benchmarks/*.csv (opsiyonel: xu100, altin, usdtry)
- **Platform durumu:** Dataset/platform_status/platform_status_*.json

### 6.2 Ciktilar (Output/)
| Dosya | Icerik |
|-------|--------|
| combined_tefas_data_*.parquet | Birlesik fiyat/AUM verisi |
| tefas_financial_metrics_*.parquet/csv | Tum metrikler |
| advanced_portfolio_recommendations_*.parquet/csv | Skorlu metrikler |
| backtest_walkforward_*.csv | Backtest kat detaylari |
| score_history_*.parquet | Skor gecmisi (sinyaller icin) |

### 6.3 Raporlar (Reports/)
- tefas_premium_rapor_yatirim.pdf — Ana analiz raporu
- tefas_karsilastirma_yatirim.pdf — Karsilastirma raporu

---

## 7. Bagimliliklar

### Zorunlu
`
pandas >= 2.0
numpy >= 1.24
matplotlib >= 3.7
reportlab >= 4.0
pyarrow >= 14.0
`

### Opsiyonel
`
[dev]     pytest >= 7.0
[fetch]   cloudscraper >= 1.2
[dashboard] streamlit >= 1.35
           plotly >= 5.20
`

---

## 8. Test Kapsami

15 test dosyasi, tum modulleri kapsayan **altin-deger testleri**:

| Test Dosyasi | Kapsam |
|-------------|--------|
| test_metrics.py | CAGR, Sharpe, Sortino, Calmar, VaR/CVaR, drawdown |
| test_portfolio.py | Kovaryans, portfoy volatilitesi, risk katkilari |
| test_io_and_scoring.py | Percentile-rank, composite skor |
| test_themes.py | Tema siniflandirmasi, akrani istatistikleri |
| test_holdings.py | FIFO pozisyonlar, XIRR, TWR |
| test_allocation.py | Portfoy kurulumu, rebalans |
| test_backtest.py | Walk-forward dogrulama |
| test_benchmarks.py | Benchmark yukleme, goreli metrikler |
| test_comparison.py | Karsilastirma modu |
| test_config_runtime.py | Config yukleme/kaydetme |
| test_dashboard.py | Dashboard veri yukleme |
| test_data_quality.py | Fiyat serisi kalite kontrolu |
| test_download_benchmarks.py | Benchmark indirme |
| test_report_smoke.py | PDF rapor uretimi (smoke test) |
| test_rebalance_signals.py | Sinyal uretimi |

**Calistirma:**
`
python -m pytest -q
python -m pytest tests/test_metrics.py
`

---

## 9. Metodoloji Duzeltmeleri (v1 -> v2)

| # | Bulgu | v1 | v2 |
|---|-------|----|----|
| 1 | Orkestrasyon | Her asama ayri subprocess, CSV 3x okunur | In-process, bellekte aktarim -> 3.5x hiz |
| 2 | Ara format | CSV (37.6 MB, tipsiz) | Parquet (8.7 MB, tipli) -> 4.3x kucuk |
| 3 | Testler | Yok | Her formül saf + 56+ test |
| 4 | CLI | ~8 ayri script | Tek tefas komutu |
| 5 | Olu kod | Legacy raporlar, optimizer/stress | Yalnizca gerekli yollar |
| 6 | Encoding | Her script'te tekrar | Tek yerde (io_utils) |
| 7 | Ortak pencere | Farkli gecmis uzunluklari | Son 252 gozlem (esit kiyas) |
| 8 | rf filtresi | Eleme kriteri | Yalnizca bilgilendirici bayrak |
| 9 | Stopaj sezgisi | Enflasyon+%15 vergi | Kaldirildi (boyutsal hata) |
| 10 | Cift sayim | Consistency drawdown/Sortino tekrar kullaniyor | Yalnizca pozitif gun/ay |

---

## 10. Dashboard Sayfalari

| Sayfa | Icerik |
|-------|--------|
| Genel Bakis | KPI kartlari, ilk 10 fon |
| Fon Kesif | Tema/skor/AUM filtreleri, risk-getiri haritasi |
| Fon Detay | Buyume, drawdown, yuvarlanan metrikler |
| Portfoyum | Islem defteri editoru, K/Z, XIRR/TWR |
| Denge & Sinyal | Model sapmasi, rebalans, risk katkilari |

Dashboard yalnizca Output/*.parquet okur; pipeline'dan bagimsizdir.

---

## 11. Bilincli Olarak Yapilmayanlar

- Web servisi (REST API)
- Veritabani (PostgreSQL/SQLite)
- Async/DAG orkestrasyon (Airflow/Prefect)
- Eklenti mimarisi
- Gercek zamanli veri akisi

**Neden:** Veri ~500 fon icin aylik CSV; dogru olcek, parquet onbellekli tek bir Python paketi + CLI.

---

## 12. Hizli Baslangic

`
# 1. Sanal ortam kurulumu
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"

# 2. Calistirma
.venv/Scripts/python -m tefas run --fund-type YAT --risk-free-rate 45

# 3. Testler
.venv/Scripts/python -m pytest -q

# 4. Dashboard (opsiyonel)
.venv/Scripts/python -m pip install -e ".[dashboard]"
tefas dashboard
`

---

## 13. Onemli Notlar

- **Bu araç yatýrým tavsiyesi vermez.** Gecmis performans gelecek getiriyi garanti etmez.
- portfolio_transactions.csv kisisel veri icerer ve .gitignore'dadir.
- TEFAS API token'i periyodik olarak yenilenmelidir (HTTP 401/403 hatasi alinirsa).
- Benchmark serileri opsiyoneldir; yoksa Beta/Alpha/TE/IR metrikleri NaN kalir.

## 14. Ust Seviye Oneri Mimarisi

Bu calismadan sonra sistemin urun hedefi "aciklanabilir, risk profiline uygun fon oneri sistemi"dir. Skorlama ve karar katmani ayrilmistir:

- `tefas/scoring.py`: composite/profil skorlarini uretir.
- `tefas/model_config.py`: model surumu, skor agirliklari ve oneri ayarlari icin merkezi audit kaynagidir. Scored ciktilar `Model_Version` tasir.
- `tefas/allocation.py`: uygunluk filtresi, profil bazli siralama, portfoy secim kurallari, izleme listesi ve karar bayraklarini uretir.
- AUM karar skorunun kendisi degil, likidite/uygunluk sinyalidir.
- 1 yildan kisa gecmisli fonlar ana oneriden ayrilir ve izleme listesi adayi olarak etiketlenir.

Walk-forward validasyon `tefas/validation.py` uzerinden urunlestirilmistir. PDF ve dashboard ayni ozet fonksiyonunu kullanir; backtest CSV yoksa sessiz gecilmez, kontrollu uyari verilir. Ozet; kat sayisi, ufuk bazli sonuclar, ortalama fark, medyan fark, hit-rate ve varsa turnover bilgisini gosterir.

PDF raporu karar akisi etrafinda guclendirildi: Karar Ozeti, Onerilen Portfoy, Uyari Bayraklari, Model Dogrulama, Risk Katkisi ve Fon Detaylari. Dashboard'da mevcut sayfalar korunurken `Karar Merkezi` eklendi.

Kapsam disi: Bu turda yeni KAP/EVDS/harici veri entegrasyonu, veritabani tasimasi veya gercek zamanli veri akisi eklenmedi. Uygulama mevcut `Dataset/`, mevcut benchmark klasoru, `Output/*.parquet` ve mevcut backtest CSV ciktilarini okur.

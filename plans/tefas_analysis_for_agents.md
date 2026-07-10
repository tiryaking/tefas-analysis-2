# TEFAS Fon Analiz Sistemi v2 — Kapsamlı Proje Analizi (Agent Rehberi)

> **Hazırlanma Tarihi:** 09.07.2026
> **Proje:** `tefas-analiz` v2.0.0
> **Python:** >= 3.10
> **Repo:** https://github.com/tiryaking/tefas-analysis-2.git
> **Branch:** fix/fund-selection-metrics

---

## 1. Proje Amacı ve Kapsamı

**TEFAS Fon Analiz Sistemi**, Türkiye Elektronik Fon Alım Satım Platformu (TEFAS) verilerini analiz eden kantitatif bir finansal analiz aracıdır. Bu v2 sürümü, eski `Tefas_New` projesinin **aynı mimariyle ama temiz, test edilmiş ve hızlı** şekilde yeniden inşa edilmiş halidir.

### 1.1 Temel Mimari Akışı

```
Dataset/*.csv → [ETL] → combined → [Metrics] → met + combined → [Scoring] → scored → [Report] → PDF
                                          ↘                ↘
                                     Benchmark verisi    Skor Geçmişi (birikir)
```

### 1.2 CLI Komutları

```bash
tefas run          # Tüm pipeline (ETL → Metrics → Score → Report)
tefas compare      # Belirli fonları karşılaştır
tefas etl          # Yalnızca ETL aşaması
tefas metrics      # Metrics aşaması (önbellekten combined okur)
tefas score        # Scoring aşaması (önbellekten combined + metrics okur)
tefas report       # PDF rapor üretimi
tefas backtest     # Walk-forward doğrulama
tefas holdings     # Kişisel portföy takibi (show|returns|check)
tefas dashboard    # İnteraktif web paneli (Streamlit)
```

### 1.3 Veri Kaynakları

- **`Dataset/{Yatirim|Emeklilik}/*.csv`** — TEFAS tarihsel fiyat/AUM verileri
- **`Dataset/platform_status/platform_status_{yatirim|emeklilik}.json`** — Aktif fon listesi
- **`Dataset/benchmarks/*.csv`** — (Opsiyonel) Dış benchmark endeks serileri
- **`Output/*.parquet`** — Pipeline ara çıktıları (parquet formatında)
- **`portfolio_transactions.csv`** — (Opsiyonel) Kişisel portföy işlem defteri

### 1.4 Çıktılar

- **PDF Rapor:** `Reports/tefas_premium_rapor_{yatirim|emeklilik}.pdf`

---

## 2. Proje Dizin Yapısı

```
C:\temp\Tefas_New2\
├── .gitignore
├── pyproject.toml                 # Paket yapılandırması
├── README.md                      # Ana dokümantasyon
├── NEXT_LEVEL_IMPLEMENTATION_PLAN.md  # Ürün yol haritası
├── tefas.config.json              # Çalıştırma ayarları
├── filter_config.txt              # Filtre dosyası ([INCLUDE]/[EXCLUDE])
├── comparison_config.txt          # Karşılaştırma fon kodları
├── portfolio_transactions.csv     # Kişisel portföy (gitignore'dadır)
├── portfolio_transactions.example.csv  # Örnek işlem defteri
│
├── tefas/                         # Ana paket (Python kaynakları)
│   ├── __init__.py                # v2.0.0
│   ├── __main__.py                # python -m tefas girişi
│   ├── cli.py                     # Tek CLI giriş noktası (argparse)
│   ├── config.py                  # Merkezi konfigürasyon (yollar, sabitler)
│   ├── etl.py                     # ETL: CSV → combined DataFrame
│   ├── metrics.py                 # Finansal metrik motoru
│   ├── scoring.py                 # Skorlama (percentile-rank, composite, profil)
│   ├── model_config.py            # Versioned model konfigürasyonu
│   ├── pipeline.py                # Pipeline orkestratörü
│   ├── report.py                  # PDF rapor üretimi (ReportLab)
│   ├── charts.py                  # Matplotlib grafik üreticileri + prep fonksiyonları
│   ├── allocation.py              # Portföy kurulumu ve tahsis mantığı
│   ├── backtest.py                # Walk-forward doğrulama
│   ├── benchmarks.py              # Benchmark veri katmanı + göreli metrikler
│   ├── holdings.py                # Kişisel portföy takibi (XIRR, TWR)
│   ├── portfolio.py               # Kovaryans-temelli portföy riski
│   ├── themes.py                  # Fon teması sınıflandırması
│   ├── comparison.py              # Karşılaştırma mantığı
│   ├── validation.py              # Walk-forward özetleri
│   ├── narrative.py               # Metin/biçimlendirme yardımcıları
│   ├── data_quality.py            # Veri kalitesi kontrolleri
│   ├── io_utils.py                # Ortak G/Ç yardımcıları
│   ├── tefas_web.py               # TEFAS web scraping (opsiyonel)
│   └── __pycache__/               # Bytecode önbelleği
│
├── tests/                         # Test dosyaları (20 adet)
├── Dataset/                       # Veri setleri (gitignore'da olabilir)
├── Output/                        # Pipeline çıktıları
├── Reports/                       # PDF raporlar
└── plans/                         # Plan ve analiz dosyaları
    └── tefas_analysis_for_agents.md  (bu dosya)
```

- **Karşılaştırma PDF:** `Reports/tefas_karsilastirma_{yatirim|emeklilik}.pdf`

---

## 3. Modül Detaylı Analizi

### 3.1 `config.py` — Merkezi Konfigürasyon

**Amaç:** Tüm yolları, sabitleri ve makro oranları tek yerde toplar.

**Önemli Sınıflar/Sabitler:**
- `PROJECT_ROOT`, `DATASET_DIR`, `OUTPUT_DIR`, `REPORTS_DIR` — Dizin yolları
- `FUND_TYPE_MAP = {"YAT": "Yatirim", "EMK": "Emeklilik"}`
- `MIN_DATA_POINTS = 20` — Asgari veri noktası
- `TRADING_DAYS_PER_YEAR = 252`
- `SCORING_LOOKBACK_DAYS = 252` — Ortak gerilemeli pencere
- `RETURN_FULL_CREDIBILITY_DAYS = 189` — Getiri güvenilirlik eşiği
- `THEME_MIN_FUNDS = 5` — Tema medyanı için asgari fon sayısı
- `DATA_QUALITY_MAX_DAILY_MOVE = 35.0` — Maksimum günlük hareket (%)
- `DAILY_RETURN_CLIP = 25.0` — Winsorize bandı
- `AUM_BONUS_THRESHOLD = 50` — AUM eşiği (milyon TL)
- `MacroRates` dataclass — `risk_free_rate`, `inflation`, `benchmark_return`
- `Paths` dataclass — Fon tipine göre tüm giriş/çıkış yolları
- `macro()` / `reset_macro_cache()` — Makro oranlar (config dosyasından)
- `paths_for(fund_type)` — Paths dataclass üreticisi

### 3.2 `etl.py` — ETL Katmanı

**Amaç:** Dataset CSV'lerini temiz, birleşik bir DataFrame'e dönüştürür.

**Kilit Fonksiyonlar:**
- `load_combined(fund_type, include, exclude, active_only)` → Ana ETL:
  1. CSV'leri `read_tefas_csv` ile okur
  2. `pd.concat` ile birleştirir
  3. `(Fon Kodu, Tarih)` üzerinde `keep="last"` dedup
  4. Include/exclude anahtar kelime filtreleri
  5. `active_only=True` → platform_status.json'dan aktif fon filtresi
- `active_fund_codes(path)` — JSON'dan aktif kodları okur
- `_keyword_mask(series, keywords)` — VEYA mantığı ile keyword eşleştirme

**Önemli:** Aktif fon filtresi için `platform_status.json` zorunludur; dosya yoksa `FileNotFoundError`.

- **CSV/Parquet:** `Output/` altında metrik, skor, combined, backtest, skor geçmişi

### 3.3 `metrics.py` — Finansal Metrik Motoru

**Amaç:** Her fon için finansal metrikleri hesaplar (saf, test edilebilir fonksiyonlar).

**Kilit Fonksiyonlar:**

| Fonksiyon | Açıklama |
|-----------|----------|
| `annualized_volatility(daily_returns_pct)` | σ × √252 |
| `cagr(first_price, last_price, n_days)` | Bileşik yıllık getiri |
| `max_drawdown(prices)` | En büyük tepe-dip düşüşü |
| `sharpe_ratio(ann_return, ann_vol, rf)` | (R − rf) / σ |
| `sortino_ratio(daily, ann_return, rf)` | Aşağı yönlü sapma tabanlı |
| `calmar_ratio(ann_return, mdd)` | CAGR / MaxDD |
| `value_at_risk(returns, confidence)` | Tarihsel VaR |
| `conditional_var(returns, confidence)` | Tarihsel CVaR |
| `compute_fund_metrics(group, rf)` | Tek fon için tüm metrikler |
| `compute_metrics(combined, rf, ...)` | Tüm fonlar için metrik tablosu |

**Metrik Çıktıları:** `Veri_Kalitesi`, `Yillik_Getiri`, `Yillik_Getiri_Kurulus`, `Yillik_Volatilite`, `Sharpe_Orani`, `Sortino_Orani`, `Calmar_Orani`, `Max_Drawdown`, `VaR_95/99`, `CVaR_95`, `Skewness`, `En_Kotu_Gun`, `En_Iyi_Gun`, `Pozitif_Gun_Orani`, `Pozitif_Ay_Orani`, `Fon_Toplam_Deger_Milyon_TL`, `Fon_Yasi_Yil`, `Veri_Noktasi_Sayisi`, `Rf_Ustu` (bilgilendirici bayrak), `Uygun` (AUM/yaş seçim maskesi)

### 3.4 `scoring.py` — Skorlama Motoru

**Amaç:** Metrikleri percentile-rank tabanlı composite ve profil skorlarına dönüştürür.

**Kilit Fonksiyonlar:**
- `shrunk_annual_return(df)` — Shrinkage: `w * getiri + (1-w) * tema_medyan`
- `_pct_rank(s, ascending)` — Yüzdelik sıra (0–100), outlier dayanıklı
- `_triangular(pct_series, peak)` — Bant uyum skoru
- `_consistency(df)` — Tutarlılık (çifte sayım önlenmiş)
- `_momentum(df)` — 3 aylık getiri trendi
- `_risk_profiles(df, consistency)` — 4 profil skoru
- `score_funds(metrics, combined, rf)` → Ana skorlama

**Profil Skor Ağırlıkları:**
```
Conservative → vol_low(0.40), dd_low(0.30), pos_days(0.15), consistency(0.15)
Balanced     → sortino(0.30), calmar(0.25), vol_band_mid(0.20), return(0.15), consistency(0.10)
Moderate     → sharpe(0.40), return(0.25), vol_band_mid(0.20), consistency(0.15)
Aggressive   → return(0.40), momentum(0.25), vol_pct(0.15), calmar(0.10), calmar_gate(0.10)
```

**Composite Skor Ağırlıkları:**
```
sharpe(0.25) + sortino(0.15) + drawdown(0.20) + return(0.20) + theme_relative(0.05) + consistency(0.075) + liquidity(0.075)
```



### 3.5 `model_config.py` — Versioned Model Konfigürasyonu

**Amaç:** Skor ve öneri model ayarlarını versiyonlar.

- `ModelConfig` dataclass (frozen): `version`, `overall_weights`, `profile_weights`, `recommendation_settings`, `source`
- `load(path)` → JSON'dan yükler; hatalı/eksik dosyada varsayılanlara düşer
- `current()` → Singleton cache (`_MODEL`)
- `tefas.model.json` dosyasından okur (yoksa varsayılan)

### 3.6 `pipeline.py` — Pipeline Orkestratörü

**Amaç:** Tüm pipeline'ı bellekte çalıştırır (in-process).

- `Artifacts` dataclass — Çıktı dosya yolları
- `run(fund_type, rf, ...)` → ETL → Metrics (benchmark) → Scoring → Report + Skor geçmişi
- `run_comparison(fund_type, rf, codes)` → Karşılaştırma modu
- `_read_parquet(path)` → Önbellekten okuma

### 3.7 `allocation.py` — Portföy Kurulumu ve Tahsis

**Amaç:** Portföy seçim mantığı (PDF/dashboard ortak).

**Kilit Fonksiyonlar:**
- `add_decision_flags(df)` — Karar bayrakları
- `build_portfolio(df)` → Örnek portföy (tema tavanı 1)
- `portfolio_expected(portfolio)` → Ağırlıklı getiri + vol bandı
- `new_opportunities(df, combined)` → Yeni fırsat taraması
- `rebalance_suggestions(...)` → Rebalans önerileri

**Kurallar:** Tema tavanı 1, kısa geçmiş hariç, AUM likidite sinyali.

### 3.8 `backtest.py` — Walk-Forward Doğrulama

**Amaç:** Skor ağırlıklarının ileriye dönük değerini ölçer.

**Yöntem:** Her ay sonu t: t'ye kadar veriyle skorla → portföy kur → t+h getirisi → evren kıyası.

**Çıktı:** `BacktestResult.folds`, `.summary`, `.avg_turnover`

### 3.9 `validation.py` — Walk-Forward Özet Paylaşımı

- `WalkForwardSummary` dataclass: `table`, `status` ("ok"|"missing"|"empty"|"invalid"), `message`, `source`
- `summarize_walk_forward_csv(path)` → CSV özeti
- `backtest_summary_from_csv(path)` → Geriye-uyum wrapper

### 3.10 `benchmarks.py` — Benchmark Metrikleri

- `THEME_BENCHMARK` — Tema → benchmark eşleme
- `load_benchmarks()` → `Dataset/benchmarks/*.csv` yükler
- `relative_metrics(fund_prices, bench_prices, rf)` → Beta, Alpha, TE, IR
- `add_relative_metrics(met, combined, benchmarks, rf)` → Metrik tablosuna ekle

**Önemli:** Opsiyonel; benchmark yoksa pipeline çalışır. Skorlara dahil edilmez.

### 3.11 `portfolio.py` — Portföy Riski (Kovaryans)

- `returns_matrix(combined, codes)` → Günlük getiri matrisi
- `shrunk_covariance(returns_df)` → Ledoit-Wolf büzülmüş kovaryans
- `portfolio_volatility_from_returns(rets, w, cov)` → σ_p = sqrt(wᵀΣw)
- `risk_contributions(rets, w)` → Varyansa yüzde katkı
- `portfolio_risk(combined, portfolio)` → Risk özeti dict

### 3.12 `holdings.py` — Kişisel Portföy Takibi

- `load_transactions(path)` → İşlem defterini oku/doğrula
- `compute_positions(df)` → FIFO pozisyon, maliyet, P&L
- `xirr(transactions)` → Para-ağırlıklı getiri (bisection, scipy yok)
- `time_weighted_return(transactions, prices)` → Zaman-ağırlıklı getiri
- `score_snapshot(scored, as_of)` → Skor geçmişi kaydı
- `append_score_history(snapshot, path)` → Geçmişe ekle

### 3.13 `themes.py` — Tema Sınıflandırması

**Temalar (11):** Para Piyasası, Borçlanma Araçları, Kira Sertifikası, Katılım, Hisse Senedi, Teknoloji, Altın & Kıymetli Maden, Emtia & Enerji, Yabancı / Endeks, Fon Sepeti, Karma / Değişken, Diğer

- `fund_theme(name)` → Anahtar kelime eşleşmesi
- `add_theme(df)` → Tema sütunu ekler
- `theme_relative_percentile(df, value_col)` → Tema içi yüzdelik
- `theme_medians(df, cols)` → Tema medyan metrikler
- `theme_median_growth(combined, codes)` → Medyan getiri endeksi

### 3.14 `report.py` — PDF Rapor (ReportLab)


### 3.15 `charts.py` — Grafik Üreticileri

**Prep Fonksiyonları (dashboard ile paylaşılır):**
- `price_pivot(combined)` → Tarih × Fon Kodu pivot
- `prep_growth(pivot, codes)` → Baz-100 büyüme
- `prep_drawdown(prices)` → Drawdown hesaplama
- `prep_monthly_returns(pivot)` → Aylık getiriler
- `prep_rolling(pivot, codes, window)` → Yuvarlanan metrikler

**Chart Fonksiyonları (PDF):** `chart_top_returns`, `chart_allocation`, `chart_risk_return`, `chart_growth_history`, `chart_correlation_heatmap`, `chart_distribution`, `chart_benchmark_bars`, `chart_sparkline`, `chart_risk_contribution`, `chart_portfolio_underwater`, `chart_category_mix`, `chart_monthly_heatmap`, `chart_rolling`, `chart_fund_detail`, `chart_monthly_bars` + karşılaştırma: `chart_cmp_growth`, `chart_cmp_periods`, `chart_cmp_scatter`, `chart_cmp_drawdown`, `chart_cmp_radar`

### 3.16 `comparison.py` — Karşılaştırma Mantığı

- `CMP_METRICS` — 17 metrik satırı
- `VERDICT_METRICS` — 8 "en iyi" ölçütü
- `RADAR_AXES` — 6 eksenli radar
- `best_index/met`, `best_code/met`, `verdict_rows/met`, `comparison_matrix/met`, `prep_radar/met`

### 3.17 `data_quality.py` — Veri Kalitesi

- `screen_price_series(prices)` → Kalite: OK / SUSPECT_JUMP / INSUFFICIENT
- `clean_daily_returns(returns, clip)` → Winsorize
- `daily_returns_pct(prices)` → Günlük % getiri

### 3.18 `narrative.py` — Metin/Biçimlendirme

- `fmt(x, dec)`, `pct(x, dec)` → Biçimlendirme
- `short_name(name)` → Ad kısaltma
- `build_rationale(row)` → Fon gerekçesi
- `methodology_sections(...)` → Metodoloji belgesi

### 3.19 `io_utils.py` — G/Ç Yardımcıları

- `setup_utf8()` → Windows UTF-8 düzeltmesi
- `parse_turkish_float(value)` → Türkçe sayı ayrıştırma
- `read_tefas_csv(path)` → TEFAS CSV okuma (eski + yeni format)

### 3.20 `tefas_web.py` — TEFAS Web Scraping

- `fetch_fund_details(code)` → Web'den fon detayı (cloudscraper + urllib fallback)
- Dashboard'da "TEFAS'tan Bilgi Getir" butonu için

**Sayfa Akışı:**
1. Kapak / Makro oranlar
2. İçindekiler
3. KPI paneli (dağılım, benchmark barları)
4. Önerilen portföy (risk katkısı, drawdown, korelasyon)
5. Karar özeti ve uyarı bayrakları
6. Fon künye kartları (tear-sheet)
7. Yeni fırsatlar
8. Çeşitlendirilmiş portföy
9. Kategori/Tema kırılımı
10. Aylık getiri takvimi + yuvarlanan metrikler
11. Fon detay sayfaları (ilk 6)


---

## 4. Test Yapısı (20 test dosyası)

| Test Dosyası | Modül |
|---|---|
| `test_allocation.py` | allocation.py |
| `test_backtest.py` | backtest.py |
| `test_benchmarks.py` | benchmarks.py |
| `test_comparison.py` | comparison.py |
| `test_config_runtime.py` | config.py runtime |
| `test_dashboard.py` | dashboard |
| `test_dashboard_figures.py` | dashboard grafikleri |
| `test_data_quality.py` | data_quality.py |
| `test_download_benchmarks.py` | benchmark download |
| `test_holdings.py` | holdings.py |
| `test_io_and_scoring.py` | io_utils.py + scoring.py |
| `test_metrics.py` | metrics.py (altın değer) |
| `test_model_config.py` | model_config.py |
| `test_narrative.py` | narrative.py |
| `test_portfolio.py` | portfolio.py |
| `test_rebalance_signals.py` | allocation rebalans |
| `test_report_smoke.py` | report.py smoke test |
| `test_tefas_web.py` | tefas_web.py |
| `test_themes.py` | themes.py |
| `test_validation.py` | validation.py |

**Test çalıştırma:** `python -m pytest -q` (34 passed)

---

## 5. Önemli Tasarım Kararları ("Finding"ler)

### Finding #1 — In-process pipeline
v1: aşamalar ayrı subprocess + ~37 MB CSV üç kez okuma. v2: fonksiyon çağrısı + parquet. ~3.5× hızlı.

### Finding #2 — Parquet ara çıktıları
CSV round-trip (tip kaybı) kalktı. Rapor ve dashboard aynı parquet dosyalarını okur.

### Finding #3 — Saf, test edilebilir metrik fonksiyonları
v1: formüller gömülü, test yok. v2: her formül ayrı saf fonksiyon + altın değer testleri.

### Finding #4 — Gerçek kovaryans matrisi
v1: portföy vol "tam bağımsız ↔ tam korele" bandı. v2: Ledoit-Wolf büzülmüş kovaryans.

### Finding #5 — Skorlama + Öneri ayrıştırması
v1: `advanced_portfolio_analyzer.py` 1300+ satır, çoğu ölü kod. v2: scoring ve allocation ayrı.

### Finding #6 — Alpha/Beta/IR/Treynor kaldırıldı (skordan)
Eşit-ağırlık fon ortalaması → CAPM yorumu geçersiz. Gerçek benchmark varsa benchmarks.py'de hesaplanır, skora dahil edilmez.

### Finding #7 — Metodoloji düzeltmeleri
1. Sharpe/Sortino ortak gerilemeli pencerede (SCORING_LOOKBACK_DAYS=252)

---

## 6. Bağımlılıklar

### Çekirdek (zorunlu):
```
pandas>=2.0, numpy>=1.24, matplotlib>=3.7, reportlab>=4.0, pyarrow>=14.0
```

### Opsiyonel:
```
dev:       pytest>=7.0
fetch:     cloudscraper>=1.2
dashboard: streamlit>=1.35, plotly>=5.20, cloudscraper>=1.2
```

---

## 7. Konfigürasyon Dosyaları

### `tefas.config.json` (çalıştırma ayarları)
```json
{
  "fund_type": "YAT",
  "risk_free_rate": 65.0,
  "include": null,
  "exclude": ["ALTIN", "GÜMÜŞ", ...],
  "active_only": true,
  "keep_suspect": false,
  "min_aum": null,
  "min_fund_age": null,
  "write_report": true
}
```

### `filter_config.txt` (filtre dosyası)
```
[INCLUDE]
...
[EXCLUDE]
ALTIN
...
```

### `tefas.model.json` (model konfigürasyonu — isteğe bağlı)
```json
{
  "version": "tefas-reco-v2.1.0",
  "overall_weights": {...},
  "profile_weights": {...},
  "recommendation_settings": {...}
}
```

---

## 8. Veri Akış Şemaları

### 8.1 `tefas run` Pipeline Akışı

```
load_combined()
    ├── CSV'leri oku (read_tefas_csv)
    ├── Birleştir & dedup
    ├── Include/Exclude filtre
    ├── Aktif fon filtresi
    └── → combined.parquet
           ↓
compute_metrics()
    ├── Her fon için compute_fund_metrics
    ├── Kalite filtresi (suspect çıkar)
    ├── Rf_Ustu bayrağı
    ├── Uygun maskesi (AUM/yaş)
    └── → metrics.parquet + metrics.csv
           ↓
load_benchmarks() + add_relative_metrics()
    └── Benchmark varsa Beta/Alpha/TE/IR ekle
           ↓
score_funds()
    ├── Tema ataması
    ├── Shrinkage düzeltmesi
    ├── Consistency, Momentum
    ├── 4 Risk Profili skoru
    ├── Tema_Rel_Skor
    ├── Overall_Score (composite)
    └── → scored.parquet + scored.csv
           ↓
score_snapshot() + append_score_history()
    └── → score_history_*.parquet (biriken)
           ↓
report.generate()
    └── → Reports/tefas_premium_rapor_*.pdf
```

### 8.2 Dashboard Veri Akışı

```
Output/*.parquet (sadece okuma)
    ├── combined → price_pivot → grafikler
    ├── metrics  → metrik tabloları
    ├── scored   → skor tabloları
    ├── score_history → sinyaller
    └── backtest_walkforward_*.csv → validasyon özeti
           ↓
    Dashboard (Streamlit + Plotly)
    Sayfalar:
    ├── Genel Bakış (KPI + ilk 10)
    ├── Fon Keşif (tema/skor/AUM filtreleri + risk-getiri haritası)
    ├── Fon Detay (büyüme, drawdown, yuvarlanan metrikler)
    ├── Portföyüm (işlem defteri editörü, K/Z, XIRR/TWR)
    └── Denge & Sinyal + Karar Merkezi
```

---

## 9. Sık Yapılan Değişiklik Noktaları

| Değişiklik | Değiştirilecek Dosya |
|---|---|
| Skor ağırlıklarını değiştirmek | `model_config.py` (veya `tefas.model.json`) |
| Yeni metrik eklemek | `metrics.py` (formül) + `scoring.py` (ağırlık) + `comparison.py` (gösterim) |
| Rapor içeriğini değiştirmek | `report.py` (yerleşim) + `charts.py` (grafik) |
| Dashboard'a sayfa eklemek | Dashboard modülü (Streamlit) |
| Veri kaynağını değiştirmek | `etl.py` + `io_utils.py` |
| Çıktı formatını değiştirmek | `config.py` (Paths) + `pipeline.py` (yazma) |
| Portföy seçim kurallarını değiştirmek | `allocation.py` |
| Benchmark eşlemesini değiştirmek | `benchmarks.py` (THEME_BENCHMARK) |
| Tema sınıflandırmasını değiştirmek | `themes.py` (THEMES listesi) |

---

## 10. Git Durumu

- **Branch:** `fix/fund-selection-metrics`
- **Son Commit:** `5ea479f1e377f4d82bd48c14cdf142a556ac1b80`
- **Uzak:** `origin: https://github.com/tiryaking/tefas-analysis-2.git`
- Bu dosya: `plans/tefas_analysis_for_agents.md`

---

## 11. Agent Geliştirme Notları

### Yeni bir özellik eklerken:
1. `NEXT_LEVEL_IMPLEMENTATION_PLAN.md`'deki faz yapısını kontrol edin
2. Saf iş mantığını sunum katmanından ayırın (PDF/dashboard ortak)
3. Test yazın (altın değer, sınır durumlar)
4. Mevcut pipeline akışını bozmamaya dikkat edin
5. Mevcut konfigürasyon dosyalarıyla uyumluluğu koruyun

### Önemli Kurallar:
- `combined` = long format (Tarih, Fon Kodu, Fiyat, ...)
- `metrics` = fon başına bir satır
- `scored` = metrics + skor sütunları
- Tüm saf fonksiyonlar test edilebilir olmalı
- Pipeline asla veri kaynağı olmadan çökmemeli (graceful degradation)
- Tüm kullanıcı mesajları Türkçe
- Dashboard sadece `Output/*.parquet` ve backtest CSV okur (pipeline'dan bağımsız)
- `charts.prep_*` fonksiyonları PDF ve dashboard arasında ortak veri sağlar
- Mevcut kod konvansiyonlarına ve pattern'lerine sadık kalın




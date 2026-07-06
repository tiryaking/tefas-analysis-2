"""
Benchmark (kıyas endeksi) veri katmanı ve göreli metrikler.

scoring.py'deki karar (Alpha/Beta/Treynor/IR'nin kaldırılması) doğruydu: vekil
benchmark (eşit-ağırlık fon ortalaması) CAPM/aktif-getiri yorumunu geçersiz
kılıyordu. Bu modül o metrikleri YALNIZCA gerçek bir dış benchmark serisi
mevcutsa geri getirir:

- `Dataset/benchmarks/*.csv` dosyalarından günlük seri okunur; dosya adı
  benchmark kimliğidir (örn. `xu100.csv`, `altin.csv`, `usdtry.csv`).
  Beklenen kolonlar: Tarih (veya Date) + Deger (veya Close/Value/Fiyat).
- Her fon, adından türetilen temasına göre uygun benchmark'a eşlenir
  (`THEME_BENCHMARK`); eşlemesi olmayan temalar (örn. Para Piyasası) NaN alır.
- Beta / Jensen Alpha / Tracking Error / Information Ratio ortak gerilemeli
  pencerede, fon ile benchmark'ın KESİŞEN günlerinde hesaplanır.

Benchmark verisi tamamen OPSİYONELDİR: klasör yoksa/boşsa pipeline aynen
çalışır ve bu sütunlar NaN kalır. Skorlara dahil edilmez (ağırlıklar
walk-forward doğrulamadan geçmeden skor bileşimi değiştirilmiyor; bkz.
backtest.py) — yalnızca metrik tablosu ve rapor bağlamı içindir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, themes
from .metrics import cagr

BENCHMARK_DIR = config.DATASET_DIR / "benchmarks"

# Tema → benchmark kimliği (dosya adı kökü). Yalnızca net eşleşmeler; karma/
# para-piyasası gibi temalara piyasa betası anlamlı atfedilemez → eşleme yok.
THEME_BENCHMARK = {
    "Hisse Senedi": "xu100",
    "Teknoloji": "xu100",
    "Altın & Kıymetli Maden": "altin",
    "Yabancı / Endeks": "usdtry",
}

# Göreli metrikler için asgari ortak (fon ∩ benchmark) getiri gözlemi.
MIN_RELATIVE_OBS = 60

_DATE_COLS = ("Tarih", "Date", "date", "TARIH", "tarih")
_VALUE_COLS = ("Deger", "Değer", "Close", "close", "Value", "value", "Fiyat")


def _read_series(path) -> pd.Series | None:
    """Tek benchmark CSV'sini günlük fiyat/endeks serisine çevirir."""
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Benchmark okunamadı ({path.name}): {e}")
        return None
    date_col = next((c for c in _DATE_COLS if c in df.columns), None)
    val_col = next((c for c in _VALUE_COLS if c in df.columns), None)
    if date_col is None or val_col is None:
        print(f"[WARN] Benchmark kolonları bulunamadı ({path.name}); "
              f"beklenen: Tarih + Deger/Close.")
        return None
    idx = pd.to_datetime(df[date_col], errors="coerce")
    vals = df[val_col]
    if vals.dtype == object:
        sv = vals.astype(str)
        if sv.str.contains(",", regex=False).any():   # Türkçe format: 1.234,56
            sv = sv.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        vals = sv
    vals = pd.to_numeric(vals, errors="coerce")
    s = pd.Series(vals.to_numpy(), index=idx).dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) < MIN_RELATIVE_OBS:
        print(f"[WARN] Benchmark serisi çok kısa ({path.name}: {len(s)} gözlem); atlandı.")
        return None
    s.name = path.stem.lower()
    return s


def load_benchmarks(bench_dir=None) -> dict[str, pd.Series]:
    """`Dataset/benchmarks/` altındaki tüm serileri yükler; klasör yoksa {}."""
    d = bench_dir if bench_dir is not None else BENCHMARK_DIR
    if not d.exists():
        return {}
    out = {}
    for f in sorted(d.glob("*.csv")):
        s = _read_series(f)
        if s is not None:
            out[s.name] = s
    return out


def relative_metrics(fund_prices: pd.Series, bench_prices: pd.Series,
                     risk_free_rate: float,
                     trading_days: int = config.TRADING_DAYS_PER_YEAR) -> dict:
    """
    Fonun benchmark'a göre metrikleri — tümü yüzde/yıllık bazda:

        Beta  = cov(f, b) / var(b)                     (günlük getirilerden)
        Alpha = fon_yıllık − [rf + Beta·(bench_yıllık − rf)]   (Jensen, %)
        Tracking_Error = std(f − b, ddof=1)·√252        (%)
        Information_Ratio = (fon_yıllık − bench_yıllık) / TE

    Yıllık getiriler iki serinin de KESİŞEN penceresinin uç fiyatlarından
    (geometrik) hesaplanır; < MIN_RELATIVE_OBS ortak gözlemde NaN döner.
    """
    nan = {"Beta": np.nan, "Alpha": np.nan, "Tracking_Error": np.nan,
           "Information_Ratio": np.nan, "Benchmark_Gozlem": 0}
    if fund_prices is None or bench_prices is None:
        return nan
    f = fund_prices.dropna()
    common = f.index.intersection(bench_prices.index)
    if len(common) < MIN_RELATIVE_OBS + 1:
        return nan
    fp = f.loc[common].astype("float64")
    bp = bench_prices.loc[common].astype("float64")
    fr = fp.pct_change().dropna() * 100.0
    br = bp.pct_change().dropna() * 100.0
    if len(fr) < MIN_RELATIVE_OBS:
        return nan

    var_b = br.var()          # ddof=1
    if pd.isna(var_b) or var_b <= 0:
        return nan
    beta = float(fr.cov(br) / var_b)

    n = len(common) - 1
    fund_ann = cagr(fp.iloc[0], fp.iloc[-1], n, trading_days, min_days=MIN_RELATIVE_OBS)
    bench_ann = cagr(bp.iloc[0], bp.iloc[-1], n, trading_days, min_days=MIN_RELATIVE_OBS)
    if pd.isna(fund_ann) or pd.isna(bench_ann):
        return nan
    alpha = float(fund_ann - (risk_free_rate + beta * (bench_ann - risk_free_rate)))

    diff = fr - br
    te = float(diff.std() * np.sqrt(trading_days))
    ir = float((fund_ann - bench_ann) / te) if te > 0 else np.nan

    return {"Beta": round(beta, 4), "Alpha": round(alpha, 4),
            "Tracking_Error": round(te, 4),
            "Information_Ratio": round(ir, 4) if pd.notna(ir) else np.nan,
            "Benchmark_Gozlem": int(len(fr))}


def add_relative_metrics(met: pd.DataFrame, combined: pd.DataFrame,
                         benchmarks: dict[str, pd.Series],
                         risk_free_rate: float) -> pd.DataFrame:
    """
    Metrik tablosuna Benchmark / Beta / Alpha / Tracking_Error /
    Information_Ratio sütunlarını ekler. Fonun benchmark'ı temasından türetilir
    (THEME_BENCHMARK); veri yoksa veya tema eşlenmemişse NaN. Diğer risk
    metrikleriyle tutarlılık için fon fiyatları ortak gerilemeli pencereye
    (`SCORING_LOOKBACK_DAYS`) kırpılır.
    """
    met = met.copy()
    cols = ("Benchmark", "Beta", "Alpha", "Tracking_Error", "Information_Ratio")
    for c in cols:
        met[c] = np.nan
    met["Benchmark"] = met["Benchmark"].astype(object)
    if not benchmarks or met.empty or combined is None or combined.empty:
        return met

    c = combined.copy()
    c["Tarih"] = pd.to_datetime(c["Tarih"])
    lookback = config.SCORING_LOOKBACK_DAYS
    by_code = {code: g for code, g in c.groupby("Fon Kodu")}

    n_done = 0
    for i, row in met.iterrows():
        code = row["Fon Kodu"]
        theme = themes.fund_theme(row.get("Fon Adi"))
        bname = THEME_BENCHMARK.get(theme)
        if bname is None or bname not in benchmarks:
            continue
        g = by_code.get(code)
        if g is None:
            continue
        g = g.sort_values("Tarih")
        prices = pd.Series(g["Fiyat"].to_numpy(), index=g["Tarih"]).tail(lookback + 1)
        rel = relative_metrics(prices, benchmarks[bname], risk_free_rate)
        if pd.notna(rel["Beta"]):
            met.loc[i, "Benchmark"] = bname
            for k in ("Beta", "Alpha", "Tracking_Error", "Information_Ratio"):
                met.loc[i, k] = rel[k]
            n_done += 1
    print(f"[INFO] Benchmark metrikleri: {n_done} fon için hesaplandı "
          f"(seriler: {', '.join(sorted(benchmarks))}).")
    return met

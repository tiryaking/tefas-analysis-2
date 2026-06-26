"""
Finansal metrik motoru.

FINDING #3 — v1'de hiç test yoktu ve tüm formüller `compute_fund_metrics`
içine satır-içi gömülüydü. Burada her formül **saf, ayrı bir fonksiyon**:
`annualized_volatility`, `cagr`, `sharpe_ratio`, `sortino_ratio`,
`max_drawdown`, `calmar_ratio`. tests/test_metrics.py bunları elle hesaplanmış
altın değerlere karşı doğrular. `compute_fund_metrics` artık bu fonksiyonları
birleştirir; mantık v1 ile birebir aynıdır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .data_quality import (
    screen_price_series, clean_daily_returns,
    QUALITY_OK, QUALITY_SUSPECT,
)

TD = config.TRADING_DAYS_PER_YEAR        # 252
MAX_RATIO = 100.0
MIN_DOWNSIDE_ANNUAL = 0.15
MIN_DD = 0.2

# ─────────────────────────────────────────────────────────────────────────────
# Saf metrik fonksiyonları (test edilebilir)
# ─────────────────────────────────────────────────────────────────────────────

def annualized_volatility(daily_returns_pct, trading_days: int = TD) -> float:
    """
    Yıllık volatilite = günlük getiri std (örneklem, ddof=1) × √252.
    Girdi yüzde cinsinden günlük getiriler; çıktı yüzde.
    """
    s = pd.Series(daily_returns_pct, dtype="float64").dropna()
    if len(s) < 2:
        return np.nan
    std = s.std()  # pandas: ddof=1
    if pd.isna(std) or std <= 0:
        return np.nan
    return float(std * np.sqrt(trading_days))


def cagr(first_price: float, last_price: float, n_trading_days: int,
         trading_days: int = TD, min_days: int = 63, cap: float = 500.0) -> float:
    """
    Bileşik yıllık getiri (CAGR), gerçek uç fiyatlardan. Yüzde cinsinden.
    Aritmetik ortalama bileşiklemesinin aşırı tahminini önler; volatilite ile
    tutarlıdır (her ikisi de tüm geçmiş üzerinden).
    """
    if n_trading_days < min_days:
        return np.nan
    if pd.isna(first_price) or pd.isna(last_price) or first_price <= 0 or last_price <= 0:
        return np.nan
    years = n_trading_days / trading_days
    total_return = last_price / first_price - 1.0
    value = ((1.0 + total_return) ** (1.0 / years) - 1.0) * 100.0
    if pd.isna(value) or abs(value) >= cap:
        return np.nan
    return float(value)


def max_drawdown(prices) -> float:
    """En büyük tepe-dip düşüşü, pozitif yüzde olarak (örn. 12.5 => %12.5 kayıp)."""
    arr = np.asarray(prices, dtype="float64")
    arr = arr[(~np.isnan(arr)) & (arr > 0)]
    if arr.size < 2:
        return np.nan
    peak = np.maximum.accumulate(arr)
    dd = (peak - arr) / peak * 100.0
    return float(round(dd.max(), 4))


def sharpe_ratio(annual_return: float, annual_vol: float, risk_free_rate: float) -> float:
    """Sharpe = (yıllık getiri − rf) / yıllık volatilite. Tümü yüzde."""
    if pd.isna(annual_return) or pd.isna(annual_vol) or annual_vol <= 0:
        return np.nan
    return float((annual_return - risk_free_rate) / annual_vol)


def sortino_ratio(daily_returns_pct, annual_return: float, risk_free_rate: float,
                  trading_days: int = TD) -> float:
    """
    Kanonik Sortino: aşağı yönlü sapma TÜM gözlemler üzerinden
        sqrt( mean( min(R_t − T, 0)^2 ) ) × √252,  T = günlük rf eşiği.
    ±MAX_RATIO ile sınırlandırılır.
    """
    s = pd.Series(daily_returns_pct, dtype="float64").dropna()
    if len(s) < 2 or pd.isna(annual_return):
        return np.nan
    daily_rf = risk_free_rate / trading_days
    downside = np.minimum(s.to_numpy() - daily_rf, 0.0)
    annualized_downside = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(trading_days))
    if pd.isna(annualized_downside) or annualized_downside < MIN_DOWNSIDE_ANNUAL:
        return np.nan
    ratio = (annual_return - risk_free_rate) / annualized_downside
    return float(min(ratio, MAX_RATIO) if ratio > 0 else max(ratio, -MAX_RATIO))


def calmar_ratio(annual_return: float, mdd: float, risk_free_rate: float) -> float:
    """Calmar = (yıllık getiri − rf) / max drawdown. ±MAX_RATIO ile sınırlı."""
    if pd.isna(annual_return) or pd.isna(mdd) or mdd < MIN_DD or mdd <= 0:
        return np.nan
    ratio = (annual_return - risk_free_rate) / mdd
    return float(min(ratio, MAX_RATIO) if ratio > 0 else max(ratio, -MAX_RATIO))


def period_return(dates, prices, last_ts, offset) -> float:
    """
    Takvim-bazlı dönem getirisi (TEFAS uyumlu): `last_ts - offset` tarihine ait
    veya sonrası ilk fiyata göre son fiyatın yüzde değişimi.
    """
    n = len(prices)
    target = np.datetime64(last_ts - offset)
    mask = dates >= target
    if not mask.any():
        return np.nan
    idx = int(np.argmax(mask))
    if idx >= n - 1:
        return np.nan
    first = prices[idx]
    if pd.isna(first) or first <= 0:
        return np.nan
    return float((prices[-1] - first) / first * 100.0)


def net_return(gross_cagr: float) -> float:
    """Yönetim ücreti + stopaj sonrası net getiri (yüzde)."""
    if pd.isna(gross_cagr):
        return np.nan
    after_fee = gross_cagr - config.MANAGEMENT_FEE_RATE
    threshold = config.TUFE_RATE + config.TUFE_PLUS_THRESHOLD
    stopaj = (after_fee - threshold) * config.STOPAJ_RATE if after_fee > threshold else 0.0
    return float(after_fee - stopaj)


def real_return(nominal: float, inflation: float = config.INFLATION_RATE) -> float:
    """Fisher denklemiyle enflasyondan arındırılmış reel getiri (yüzde)."""
    if pd.isna(nominal):
        return np.nan
    return float(((1 + nominal / 100) / (1 + inflation / 100) - 1) * 100)


# ─────────────────────────────────────────────────────────────────────────────
# Fon-başına metrik birleştirme
# ─────────────────────────────────────────────────────────────────────────────

def _round(x, dec=4):
    return round(float(x), dec) if pd.notna(x) else np.nan


def compute_fund_metrics(group: pd.DataFrame, risk_free_rate: float) -> dict:
    """Tek bir fon (long-format satırlar) için tüm metrikleri hesaplar."""
    group = group.sort_values("Tarih").reset_index(drop=True)
    prices = group["Fiyat"].to_numpy()
    dates = group["Tarih"].to_numpy()
    last_price = prices[-1]
    last_ts = pd.Timestamp(dates[-1])
    n_points = len(prices)

    daily = pd.Series(prices).pct_change().replace([np.inf, -np.inf], np.nan).dropna() * 100
    clean = clean_daily_returns(daily)

    quality = screen_price_series(prices, min_points=2,
                                  max_daily_move=config.DATA_QUALITY_MAX_DAILY_MOVE)

    g1a = period_return(dates, prices, last_ts, pd.DateOffset(months=1))
    g3a = period_return(dates, prices, last_ts, pd.DateOffset(months=3))
    g6a = period_return(dates, prices, last_ts, pd.DateOffset(months=6))
    g1y = period_return(dates, prices, last_ts, pd.DateOffset(years=1))

    vol = annualized_volatility(clean)
    ann_return = cagr(prices[0], last_price, n_points - 1)
    mdd = max_drawdown(prices)

    sharpe = sharpe_ratio(ann_return, vol, risk_free_rate)
    sortino = sortino_ratio(clean, ann_return, risk_free_rate)
    calmar = calmar_ratio(ann_return, mdd, risk_free_rate)

    basit = ((prices[-1] - prices[0]) / prices[0] * 100.0) if (n_points >= 2 and prices[0] > 0) else np.nan
    skew = daily.skew() if len(daily) >= 3 else np.nan
    en_kotu = daily.min() if len(daily) >= 1 else np.nan
    en_iyi = daily.max() if len(daily) >= 1 else np.nan
    poz = (daily > 0).sum() / len(daily) * 100 if len(daily) >= 1 else np.nan

    var95 = var99 = cvar95 = np.nan
    if len(daily) >= 20:
        var95 = np.percentile(daily, 5)
        var99 = np.percentile(daily, 1)
        cvar95 = daily[daily <= var95].mean()

    # AUM
    aum = np.nan
    for c in ("Fon Toplam Deger", "Fon Toplam Değer"):
        if c in group.columns:
            latest = group[c].iloc[-1]
            if pd.notna(latest) and latest > 0:
                aum = latest / 1_000_000
            break

    # Fon yaşı
    first_date = pd.Timestamp(group["Tarih"].iloc[0])
    age_years = round((last_ts - first_date).days / 365.25, 2)

    return {
        "Fon Kodu": group["Fon Kodu"].iloc[0],
        "Fon Adi": group["Fon Adi"].iloc[0] if "Fon Adi" in group.columns else "",
        "Veri_Kalitesi": quality["quality"],
        "Max_Gunluk_Hareket": quality["max_daily_move"],
        "Veri_Noktasi_Sayisi": n_points,
        "Fon_Yasi_Yil": age_years,
        "Fon_Kurulus_Tarihi": first_date.strftime("%Y-%m-%d"),
        "Fon_Toplam_Deger_Milyon_TL": _round(aum, 2),
        "Getiri_1A": _round(g1a), "Getiri_3A": _round(g3a),
        "Getiri_6A": _round(g6a), "Getiri_1Y": _round(g1y),
        "Basit_Getiri": _round(basit),
        "Yillik_Getiri": _round(ann_return),
        "Net_Getiri_1Y": _round(net_return(ann_return)),
        "Reel_Getiri_1Y": _round(real_return(ann_return)) if config.REAL_RETURN_ENABLED else np.nan,
        "Fazla_Getiri": _round(ann_return - risk_free_rate) if pd.notna(ann_return) else np.nan,
        "Yillik_Volatilite": _round(vol),
        "Sharpe_Orani": _round(sharpe),
        "Sortino_Orani": _round(sortino),
        "Calmar_Orani": _round(calmar),
        "Max_Drawdown": _round(mdd),
        "VaR_95": _round(var95), "VaR_99": _round(var99), "CVaR_95": _round(cvar95),
        "Skewness": _round(skew),
        "En_Kotu_Gun": _round(en_kotu), "En_Iyi_Gun": _round(en_iyi),
        "Pozitif_Gun_Orani": _round(poz),
    }


def compute_metrics(combined: pd.DataFrame, risk_free_rate: float = 0.0,
                    keep_suspect: bool = False, min_aum: float | None = None,
                    min_fund_age: float | None = None) -> pd.DataFrame:
    """
    Birleşik (long) veriden fon-başına metrik tablosu üretir; veri-kalitesi,
    risksiz-faiz, AUM ve yaş filtrelerini uygular.
    """
    combined = combined.copy()
    combined["Tarih"] = pd.to_datetime(combined["Tarih"])

    records = []
    for code, group in combined.groupby("Fon Kodu"):
        try:
            records.append(compute_fund_metrics(group, risk_free_rate))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {code} işlenemedi: {e}")
    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Veri kalitesi filtresi
    suspect = df["Veri_Kalitesi"] == QUALITY_SUSPECT
    n_suspect = int(suspect.sum())
    if n_suspect and not keep_suspect:
        print(f"[INFO] Veri kalitesi: {n_suspect} şüpheli fon sıralamadan çıkarıldı.")
        df = df[~suspect].copy()

    # Risksiz faiz filtresi (getirisi rf altında olanları ele; NaN getiriyi tut)
    if risk_free_rate > 0:
        before = len(df)
        df = df[(df["Getiri_1Y"] > risk_free_rate) | (df["Getiri_1Y"].isna())].copy()
        print(f"[INFO] Risksiz faiz (%{risk_free_rate:.1f}) filtresi: {before - len(df)} fon elendi.")

    if min_aum is not None:
        df = df[(df["Fon_Toplam_Deger_Milyon_TL"] >= min_aum) |
                (df["Fon_Toplam_Deger_Milyon_TL"].isna())].copy()
    if min_fund_age is not None:
        df = df[(df["Fon_Yasi_Yil"] >= min_fund_age) | (df["Fon_Yasi_Yil"].isna())].copy()

    return df.reset_index(drop=True)

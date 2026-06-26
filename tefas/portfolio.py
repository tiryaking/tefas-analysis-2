"""
Portföy riski — kovaryans temelli.

FINDING #4 — v1'de örnek portföyün volatilitesi "tam bağımsız ↔ tam korele"
bandı (bir sezgisel) olarak gösteriliyordu; gerçek kovaryans matrisini kullanan
optimizer kodu ise ölüydü (scipy bağımlı, hiç çalışmıyordu). Burada portföy
volatilitesi gerçek günlük getiri kovaryansından hesaplanır:

    σ_p = sqrt( wᵀ · Σ · w ),   Σ = yıllıklandırılmış kovaryans (× 252)

Saf çekirdek fonksiyon `portfolio_volatility_from_returns` ayrı ve test edilir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TRADING_DAYS_PER_YEAR as TD


def returns_matrix(combined: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """
    Verilen fon kodları için ortak tarihlerde hizalanmış günlük % getiri matrisi.
    Sütun sırası `codes` içindeki mevcut kodların sırasıdır.
    """
    pivot = combined.pivot_table(index="Tarih", columns="Fon Kodu",
                                 values="Fiyat", aggfunc="first").sort_index()
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return pd.DataFrame()
    rets = pivot[avail].pct_change().replace([np.inf, -np.inf], np.nan) * 100.0
    return rets.dropna(how="any")


def portfolio_volatility_from_returns(returns_df: pd.DataFrame, weights) -> float:
    """
    Yıllık portföy volatilitesi (%) = sqrt(wᵀ Σ w), Σ = günlük kovaryans × 252.
    `weights` sütun sırasıyla hizalı olmalı ve toplamı 1 varsayılır.
    """
    if returns_df.shape[1] < 1 or len(returns_df) < 2:
        return np.nan
    w = np.asarray(weights, dtype="float64")
    cov = returns_df.cov().to_numpy() * TD          # pandas cov: ddof=1
    var = float(w @ cov @ w)
    return float(np.sqrt(max(var, 0.0)))


def average_correlation(returns_df: pd.DataFrame) -> float:
    """Köşegen-dışı ortalama ikili korelasyon (çeşitlendirme göstergesi)."""
    if returns_df.shape[1] < 2:
        return np.nan
    corr = returns_df.corr().to_numpy()
    iu = np.triu_indices_from(corr, k=1)
    vals = corr[iu]
    vals = vals[~np.isnan(vals)]
    return float(vals.mean()) if vals.size else np.nan


def portfolio_risk(combined: pd.DataFrame, portfolio: list[dict]) -> dict | None:
    """
    Örnek portföy için gerçek kovaryans-temelli risk özeti.

    Returns dict:
        portfolio_vol        : kovaryans-temelli yıllık vol (%)
        weighted_avg_vol     : ağırlıklı ortalama tekil vol (%) — çeşitlendirme yok (üst sınır)
        diversification_gain : weighted_avg_vol − portfolio_vol (%)
        avg_correlation      : ortalama ikili korelasyon
        n_used               : kovaryansta kullanılan fon sayısı
    None döner combined yoksa / yeterli ortak veri yoksa.
    """
    if combined is None or not portfolio:
        return None
    codes = [p["Fon Kodu"] for p in portfolio]
    rets = returns_matrix(combined, codes)
    if rets.shape[1] < 2 or len(rets) < 20:
        return None

    used = list(rets.columns)
    weight_by_code = {p["Fon Kodu"]: p["Agirlik"] for p in portfolio}
    w = np.array([weight_by_code[c] for c in used], dtype="float64")
    if w.sum() <= 0:
        return None
    w = w / w.sum()

    port_vol = portfolio_volatility_from_returns(rets, w)
    asset_vols = rets.std().to_numpy() * np.sqrt(TD)     # yıllık tekil vol (%)
    weighted_avg_vol = float(np.sum(w * asset_vols))

    return {
        "portfolio_vol": port_vol,
        "weighted_avg_vol": weighted_avg_vol,
        "diversification_gain": weighted_avg_vol - port_vol,
        "avg_correlation": average_correlation(rets),
        "n_used": len(used),
    }

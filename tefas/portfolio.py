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

# Bir fon çifti için kovaryans tahmininde gereken asgari ortak gözlem sayısı.
MIN_PAIR_OVERLAP = 20


def returns_matrix(combined: pd.DataFrame, codes: list[str],
                   dropna: str = "any") -> pd.DataFrame:
    """
    Verilen fon kodları için tarihlerde hizalanmış günlük % getiri matrisi.
    Sütun sırası `codes` içindeki mevcut kodların sırasıdır.

    dropna="any": yalnızca TÜM fonların verisi olan (kesişim) tarihler kalır —
    zaman-serisi hesapları (portföy drawdown) için gereklidir.
    dropna="all": tarih birleşimi korunur (yalnızca tamamen boş satırlar düşer) —
    ikili (pairwise) kovaryans için; tek bir kısa geçmişli fon pencereyi kırpmaz.
    """
    pivot = combined.pivot_table(index="Tarih", columns="Fon Kodu",
                                 values="Fiyat", aggfunc="first").sort_index()
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return pd.DataFrame()
    rets = pivot[avail].pct_change().replace([np.inf, -np.inf], np.nan) * 100.0
    return rets.dropna(how=dropna)


def shrunk_covariance(returns_df: pd.DataFrame,
                      min_overlap: int = MIN_PAIR_OVERLAP):
    """
    Yıllıklandırılmış, ikili (pairwise) + sabit-korelasyon hedefine büzülmüş
    kovaryans matrisi.

    Neden: kesişim-tabanlı kovaryans kırılgandı — portföye giren tek bir kısa
    geçmişli fon TÜM matrisin tahmin penceresini kendi geçmişine kırpıyordu.
    Burada her fon çifti kendi ortak gözlemlerini kullanır (pandas cov
    pairwise), ardından Ledoit-Wolf tarzı büzülme sabit-korelasyon hedefine
    uygulanır; yoğunluk T'ye bağlı basit bir sezgiseldir:

        δ = n_varlık / (n_varlık + T_min),  T_min = en kısa ikili pencere

    (uzun pencere → δ→0, ham tahmine güven; kısa pencere → hedefe çekilme).
    Pairwise matris pozitif yarı-tanımlı olmayabilir; negatif özdeğerler 0'a
    kırpılır.

    Returns: (cov | None, info) — info: t_min, t_max, delta, n_assets.
    """
    n = returns_df.shape[1]
    info = {"t_min": 0, "t_max": 0, "delta": np.nan, "n_assets": n}
    if n < 1:
        return None, info
    counts = returns_df.notna().astype("int64")
    overlap = (counts.T @ counts).to_numpy()
    if n > 1:
        iu = np.triu_indices(n, k=1)
        t_min, t_max = int(overlap[iu].min()), int(overlap[iu].max())
    else:
        t_min = t_max = int(overlap[0, 0])
    info.update(t_min=t_min, t_max=t_max)
    if t_min < min_overlap:
        return None, info
    cov = returns_df.cov(min_periods=min_overlap).to_numpy() * TD
    if np.isnan(cov).any():
        return None, info

    sd = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = cov / np.outer(sd, sd)
    off = corr[np.triu_indices(n, k=1)] if n > 1 else np.array([])
    off = off[np.isfinite(off)]
    rbar = float(off.mean()) if off.size else 0.0
    target = rbar * np.outer(sd, sd)
    np.fill_diagonal(target, np.diag(cov))

    delta = float(np.clip(n / (n + t_min), 0.0, 1.0))
    shrunk = (1.0 - delta) * cov + delta * target
    # PSD garantisi: simetrikleştir, negatif özdeğerleri kırp
    shrunk = (shrunk + shrunk.T) / 2.0
    vals, vecs = np.linalg.eigh(shrunk)
    if (vals < 0).any():
        shrunk = vecs @ np.diag(np.clip(vals, 0.0, None)) @ vecs.T
    info["delta"] = delta
    return shrunk, info


def _prune_short_overlap(returns_df: pd.DataFrame,
                         min_overlap: int = MIN_PAIR_OVERLAP) -> pd.DataFrame:
    """İkili ortak gözlemi `min_overlap` altında kalan çiftler varsa, en az
    gözlemli fonu çıkararak (yinelemeli) matrisi kullanılabilir hale getirir."""
    rets = returns_df
    while rets.shape[1] >= 2:
        counts = rets.notna().astype("int64")
        overlap = (counts.T @ counts).to_numpy()
        iu = np.triu_indices(rets.shape[1], k=1)
        if overlap[iu].min() >= min_overlap:
            break
        rets = rets.drop(columns=counts.sum().idxmin())
    return rets


def portfolio_volatility_from_returns(returns_df: pd.DataFrame, weights,
                                      cov: np.ndarray | None = None) -> float:
    """
    Yıllık portföy volatilitesi (%) = sqrt(wᵀ Σ w).
    Σ verilmezse günlük kovaryans × 252 (ham, kesişim örnekleminden).
    `weights` sütun sırasıyla hizalı olmalı ve toplamı 1 varsayılır.
    """
    if returns_df.shape[1] < 1 or len(returns_df) < 2:
        return np.nan
    w = np.asarray(weights, dtype="float64")
    if cov is None:
        cov = returns_df.cov().to_numpy() * TD          # pandas cov: ddof=1
    var = float(w @ cov @ w)
    return float(np.sqrt(max(var, 0.0)))


def risk_contributions(returns_df: pd.DataFrame, weights,
                       cov: np.ndarray | None = None) -> np.ndarray:
    """
    Her fonun portföy varyansına yüzde katkısı (toplamı 1.0):

        RCᵢ = wᵢ · (Σw)ᵢ / (wᵀ Σ w)

    Ağırlıktan bağımsız olarak *hangi fonun riski gerçekten sürüklediğini*
    gösterir. Σ verilmezse günlük kovaryans × 252. `weights` sütun sırasıyla hizalı.
    """
    if returns_df.shape[1] < 1 or len(returns_df) < 2:
        return np.array([])
    w = np.asarray(weights, dtype="float64")
    if cov is None:
        cov = returns_df.cov().to_numpy() * TD
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return np.full(len(w), np.nan)
    return (w * (cov @ w)) / port_var


def portfolio_drawdown(combined: pd.DataFrame, portfolio: list[dict]):
    """
    Örnek portföyün zaman içindeki kümülatif değeri ve sualtı (drawdown) eğrisi.

    Günlük getiriler ortak tarihlerde hizalanır, ağırlıklarla birleşir; kümülatif
    değer 100'e normalize edilir. Döner: (index, cumulative[%100 taban], drawdown[%]).
    None döner yeterli ortak veri yoksa.
    """
    if combined is None or not portfolio:
        return None
    codes = [p["Fon Kodu"] for p in portfolio]
    rets = returns_matrix(combined, codes)
    if rets.shape[1] < 1 or len(rets) < 10:
        return None
    weight_by_code = {p["Fon Kodu"]: p["Agirlik"] for p in portfolio}
    w = np.array([weight_by_code[c] for c in rets.columns], dtype="float64")
    if w.sum() <= 0:
        return None
    w = w / w.sum()
    port_daily = (rets.to_numpy() / 100.0) @ w              # günlük portföy getirisi (oran)
    cum = 100.0 * np.cumprod(1.0 + port_daily)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak * 100.0
    return rets.index, cum, dd


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

    Kovaryans, tarih BİRLEŞİMİ üzerinden ikili (pairwise) hesaplanır ve
    sabit-korelasyon hedefine büzülür (bkz. `shrunk_covariance`) — tek bir
    kısa geçmişli fon artık tüm matrisin penceresini kırpmaz. İkili ortak
    gözlemi yetersiz fonlar (en kısa geçmişliden başlayarak) hesap dışı
    bırakılır ve `dropped_codes` ile raporlanır.

    Returns dict:
        portfolio_vol        : kovaryans-temelli yıllık vol (%)
        weighted_avg_vol     : ağırlıklı ortalama tekil vol (%) — çeşitlendirme yok (üst sınır)
        diversification_gain : weighted_avg_vol − portfolio_vol (%)
        avg_correlation      : ortalama ikili korelasyon
        n_used               : kovaryansta kullanılan fon sayısı
        effective_days       : en kısa ikili tahmin penceresi (ortak gün)
        shrinkage            : büzülme yoğunluğu δ (0=ham, 1=hedef)
        dropped_codes        : yetersiz veri nedeniyle dışarıda kalan kodlar
    None döner combined yoksa / yeterli ortak veri yoksa.
    """
    if combined is None or not portfolio:
        return None
    codes = [p["Fon Kodu"] for p in portfolio]
    rets = returns_matrix(combined, codes, dropna="all")
    rets = rets.loc[:, rets.notna().sum() >= MIN_PAIR_OVERLAP + 1]
    rets = _prune_short_overlap(rets)
    if rets.shape[1] < 2:
        return None
    cov, cov_info = shrunk_covariance(rets)
    if cov is None:
        return None

    used = list(rets.columns)
    dropped = [c for c in codes if c not in used]
    weight_by_code = {p["Fon Kodu"]: p["Agirlik"] for p in portfolio}
    w = np.array([weight_by_code[c] for c in used], dtype="float64")
    if w.sum() <= 0:
        return None
    w = w / w.sum()

    port_vol = portfolio_volatility_from_returns(rets, w, cov=cov)
    asset_vols = np.sqrt(np.clip(np.diag(cov), 0.0, None))   # yıllık tekil vol (%)
    weighted_avg_vol = float(np.sum(w * asset_vols))
    rc = risk_contributions(rets, w, cov=cov)                # varyansa yüzde katkı

    return {
        "portfolio_vol": port_vol,
        "weighted_avg_vol": weighted_avg_vol,
        "diversification_gain": weighted_avg_vol - port_vol,
        "avg_correlation": average_correlation(rets),
        "n_used": len(used),
        "used_codes": used,
        "effective_days": cov_info["t_min"],
        "shrinkage": cov_info["delta"],
        "dropped_codes": dropped,
        "weights": {c: float(w[i]) for i, c in enumerate(used)},
        "risk_contributions": {c: float(rc[i]) for i, c in enumerate(used)} if rc.size else {},
    }

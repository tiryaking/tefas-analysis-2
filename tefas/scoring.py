"""
Skorlama: yüzdelik-sıra tabanlı composite skor, risk profilleri, Alpha/Beta,
Treynor.

FINDING #5 — v1 `advanced_portfolio_analyzer.py` 1300+ satırdı ve çoğu ölü koddu
(opsiyonel optimizer/stress/rebalancing dalları, hiç kurulu olmayan scipy'ye
bağımlı). Burada yalnızca raporun gerçekten kullandığı skorlama mantığı; formüller
v1 ile aynı (percentile-rank, üçgensel volatilite bandı, kanonik Information
Ratio, CAPM Alpha/Beta).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

TD = config.TRADING_DAYS_PER_YEAR


def _pct_rank(s: pd.Series, ascending: bool = True, fill: float = 50.0) -> pd.Series:
    """Bir metriği evren içindeki yüzdelik sırasına (0–100) çevirir. Outlier'a dayanıklı."""
    s = pd.to_numeric(s, errors="coerce")
    return (s.rank(pct=True, ascending=ascending) * 100.0).fillna(fill)


def _triangular(pct_series: pd.Series, peak: float = 50.0) -> pd.Series:
    """Tepe noktada 100, uçlara doğru lineer azalan bant-uyum skoru."""
    dist = (pct_series - peak).abs()
    return (1.0 - dist / max(peak, 100.0 - peak)) * 100.0


def _build_benchmark(combined: pd.DataFrame) -> pd.Series | None:
    """config.BENCHMARK_CODE varsa o fon; yoksa eşit-ağırlıklı kesit ortalaması (% günlük)."""
    if combined is None or combined.empty:
        return None
    pivot = combined.pivot_table(index="Tarih", columns="Fon Kodu",
                                 values="Fiyat", aggfunc="first")
    rets = pivot.pct_change().replace([np.inf, -np.inf], np.nan)
    code = config.BENCHMARK_CODE
    if code and code in rets.columns:
        bench = rets[code].dropna() * 100
        if len(bench) >= 20:
            print(f"[INFO] Benchmark: '{code}' ({len(bench)} gün)")
            return bench
        print(f"[WARN] Benchmark '{code}' yetersiz; eşit-ağırlıklıya düşülüyor.")
    bench = rets.mean(axis=1).dropna() * 100
    if len(bench) >= 20:
        print(f"[INFO] Benchmark: eşit-ağırlıklı fon sepeti ({len(bench)} gün)")
        return bench
    return None


def _consistency(df: pd.DataFrame) -> pd.Series:
    return (_pct_rank(df["Pozitif_Gun_Orani"]) * 0.40 +
            _pct_rank(df["Max_Drawdown"], ascending=False) * 0.30 +
            _pct_rank(df["Skewness"]) * 0.20 +
            _pct_rank(df["Sortino_Orani"]) * 0.10).fillna(50)


def _momentum(df: pd.DataFrame) -> pd.Series:
    return df["Getiri_1A"].fillna(0) * 0.6 + df["Getiri_3A"].fillna(0) * 0.4


def _risk_profiles(df: pd.DataFrame, rf: float, consistency: pd.Series) -> dict[str, pd.Series]:
    vol_low = _pct_rank(df["Yillik_Volatilite"], ascending=False)
    vol_pct = _pct_rank(df["Yillik_Volatilite"])
    dd_low = _pct_rank(df["Max_Drawdown"], ascending=False)
    sharpe = _pct_rank(df["Sharpe_Orani"])
    sortino = _pct_rank(df["Sortino_Orani"])
    calmar = _pct_rank(df["Calmar_Orani"])
    ret_1y = _pct_rank(df["Getiri_1Y"])
    pos_days = _pct_rank(df["Pozitif_Gun_Orani"])
    momentum_rank = _pct_rank(_momentum(df))
    vol_band_mid = _triangular(vol_pct, peak=50.0)

    rf_gate = pd.Series(np.where((df["Getiri_1Y"] > rf).fillna(False), 100.0, 20.0), index=df.index)
    calmar_gate = pd.Series(np.where((df["Calmar_Orani"] > 0).fillna(False), 100.0, 40.0), index=df.index)

    return {
        "Conservative": vol_low * 0.35 + dd_low * 0.30 + pos_days * 0.15 +
                        consistency * 0.10 + rf_gate * 0.10,
        "Balanced": sortino * 0.30 + calmar * 0.25 + vol_band_mid * 0.20 +
                    ret_1y * 0.15 + consistency * 0.10,
        "Moderate": sharpe * 0.40 + ret_1y * 0.25 + vol_band_mid * 0.20 +
                    consistency * 0.15,
        "Aggressive": ret_1y * 0.40 + momentum_rank * 0.25 + vol_pct * 0.15 +
                      calmar * 0.10 + calmar_gate * 0.10,
    }


def _information_ratio(df: pd.DataFrame, combined: pd.DataFrame, bench: pd.Series | None) -> pd.Series:
    if bench is None or combined is None:
        return pd.Series(np.nan, index=df.index)
    out = []
    for code in df["Fon Kodu"]:
        fd = combined[combined["Fon Kodu"] == code].sort_values("Tarih")
        if len(fd) < 20:
            out.append(np.nan); continue
        fr = fd.set_index("Tarih")["Fiyat"].pct_change().dropna() * 100
        common = fr.index.intersection(bench.index)
        if len(common) < 20:
            out.append(np.nan); continue
        active = (fr.loc[common] - bench.loc[common]).replace([np.inf, -np.inf], np.nan).dropna()
        te = active.std()
        out.append(float(np.clip((active.mean() / te) * np.sqrt(TD), -100, 100))
                   if (len(active) >= 20 and pd.notna(te) and te > 0) else np.nan)
    return pd.Series(out, index=df.index)


def _alpha_beta(df: pd.DataFrame, combined: pd.DataFrame, bench: pd.Series | None,
                rf: float) -> tuple[pd.Series, pd.Series]:
    alphas, betas = [], []
    if bench is None or combined is None or len(bench) < 20:
        return pd.Series([np.nan] * len(df), index=df.index), pd.Series([np.nan] * len(df), index=df.index)
    for code in df["Fon Kodu"]:
        fd = combined[combined["Fon Kodu"] == code].sort_values("Tarih")
        if len(fd) < 20:
            alphas.append(np.nan); betas.append(np.nan); continue
        fr = fd.set_index("Tarih")["Fiyat"].pct_change().replace([np.inf, -np.inf], np.nan).dropna() * 100
        common = fr.index.intersection(bench.index)
        if len(common) < 20:
            alphas.append(np.nan); betas.append(np.nan); continue
        fr, br = fr.loc[common], bench.loc[common]
        var_b = np.var(br)
        beta = np.cov(fr, br)[0, 1] / var_b if var_b > 0 else np.nan
        if pd.notna(beta):
            alpha = (fr.mean() * TD - rf) - beta * (br.mean() * TD - rf)
        else:
            alpha = np.nan
        alphas.append(alpha); betas.append(beta)
    return pd.Series(alphas, index=df.index), pd.Series(betas, index=df.index)


def score_funds(metrics: pd.DataFrame, combined: pd.DataFrame | None,
                risk_free_rate: float = 0.0) -> pd.DataFrame:
    """
    Metrik tablosuna composite skor, risk-profili skorları, Information Ratio,
    Consistency, Momentum, Alpha/Beta ve Treynor ekler. Skorlu DataFrame döndürür.
    """
    df = metrics[metrics["Veri_Noktasi_Sayisi"] >= config.MIN_DATA_POINTS].copy().reset_index(drop=True)
    if df.empty:
        return df

    bench = _build_benchmark(combined) if combined is not None else None
    consistency = _consistency(df)

    df["Consistency_Score"] = consistency.round(1)
    df["Momentum_Score"] = _momentum(df).round(2)
    df["Information_Ratio"] = _information_ratio(df, combined, bench).round(2)
    for profile, scores in _risk_profiles(df, risk_free_rate, consistency).items():
        df[f"{profile}_Score"] = scores.round(1)

    # Composite (Overall) skor — yüzdelik-sıra ağırlıklı
    liq = (_pct_rank(df["Fon_Toplam_Deger_Milyon_TL"])
           if "Fon_Toplam_Deger_Milyon_TL" in df.columns
           else pd.Series(50.0, index=df.index))
    df["Overall_Score"] = (
        0.30 * _pct_rank(df["Sharpe_Orani"]) +
        0.20 * _pct_rank(df["Sortino_Orani"]) +
        0.20 * _pct_rank(df["Max_Drawdown"], ascending=False) +
        0.20 * _pct_rank(df["Getiri_1Y"]) +
        0.05 * consistency +
        0.05 * liq
    ).round(1)

    # Alpha / Beta / Treynor
    alpha, beta = _alpha_beta(df, combined, bench, risk_free_rate)
    if alpha.notna().sum() > 0:
        df["Alpha"] = alpha.round(4).values
        df["Beta"] = beta.round(4).values
        treynor = []
        for b, r in zip(df["Beta"], df["Yillik_Getiri"]):
            if pd.notna(b) and pd.notna(r) and abs(b) >= config.MIN_BETA_FOR_TREYNOR:
                t = (r - risk_free_rate) / b
                treynor.append(round(max(-config.TREYNOR_CAP, min(config.TREYNOR_CAP, t)), 2))
            else:
                treynor.append(np.nan)
        df["Treynor_Orani"] = treynor

    return df

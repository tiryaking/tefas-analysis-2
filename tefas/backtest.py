"""
Walk-forward (ileriye dönük) doğrulama.

Skor ve profil ağırlıkları elle belirlenmiştir; bu modül önerinin İLERİYE
DÖNÜK bir değeri olup olmadığını ölçer — sistemin en büyük metodolojik açığı
buydu (öneriler tamamen örneklem-içiydi):

  Her ay sonunda t:
    1. YALNIZCA t'ye kadarki veriyle metrikler + skorlar hesaplanır
       (look-ahead yok),
    2. Örnek portföy kurulur (rapordaki _build_portfolio ile aynı kural),
    3. t → t+h ayının GERÇEKLEŞEN getirisi ölçülür ve aynı dönemde
       eşit-ağırlık evren ortalaması/medyanı ile karşılaştırılır.

Özet çıktılar: kat (fold) başına fark, isabet oranı (fark > 0 olan kat
oranı), ortalama fark ve portföy devri (turnover). ~18 aylık veriyle kat
sayısı azdır (≈12); sonuç istatistiksel kanıt değil, skorların YÖN olarak
bir sinyal taşıyıp taşımadığının sağlamasıdır.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import metrics, scoring

# Bir fiyat gözleminin "o gün için geçerli" sayılacağı azami bayatlık.
MAX_STALE_DAYS = 10


@dataclass
class BacktestResult:
    folds: pd.DataFrame        # kat × ufuk satırları
    summary: pd.DataFrame      # ufuk başına özet
    avg_turnover: float        # ardışık katlar arası ortalama devir (0–1)


def _price_asof(s: pd.Series, when: pd.Timestamp,
                max_stale_days: int = MAX_STALE_DAYS) -> float:
    """`when` tarihindeki (veya öncesindeki en yakın, bayat olmayan) fiyat."""
    idx = s.index.searchsorted(when, side="right") - 1
    if idx < 0:
        return np.nan
    d = s.index[idx]
    if (when - d).days > max_stale_days:
        return np.nan
    return float(s.iloc[idx])


def _forward_return(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """start → end basit getiri (%); uçlardan biri yoksa NaN."""
    p0 = _price_asof(s, start)
    p1 = _price_asof(s, end)
    if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
        return np.nan
    return (p1 / p0 - 1.0) * 100.0


def _turnover(prev: dict[str, float], cur: dict[str, float]) -> float:
    """İki ağırlık vektörü arasındaki tek-yön devir: 0.5 · Σ|w_i − w'_i|."""
    keys = set(prev) | set(cur)
    return 0.5 * sum(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)


def run_backtest(combined: pd.DataFrame, risk_free_rate: float, *,
                 horizons: tuple[int, ...] = (1, 3),
                 min_history_days: int = 140,
                 step_months: int = 1,
                 verbose: bool = True) -> BacktestResult | None:
    """
    Aylık walk-forward doğrulama. `combined` long-format fiyat verisidir
    (pipeline'ın 1. aşama çıktısı). None döner: hiç kat kurulamazsa.

    Evren karşılaştırması adil tutulur: her katta eşit-ağırlık/medyan evren,
    o katta skorlanabilmiş (veri kalitesi geçerli, >= MIN_DATA_POINTS gözlemli)
    fonlardan oluşur — portföyün seçim yaptığı kümenin aynısı.
    """
    from .report import _build_portfolio   # yerel: reportlab/matplotlib importunu geciktir

    c = combined.copy()
    c["Tarih"] = pd.to_datetime(c["Tarih"])
    dates = c["Tarih"].sort_values()
    data_start, data_end = dates.iloc[0], dates.iloc[-1]

    # Fon başına fiyat serileri (tek pivot yerine grup — bellek dostu, asof kolay)
    series = {code: pd.Series(g.sort_values("Tarih")["Fiyat"].to_numpy(),
                              index=pd.DatetimeIndex(g.sort_values("Tarih")["Tarih"]))
              for code, g in c.groupby("Fon Kodu")}

    # Ay sonu değerlendirme tarihleri: yeterli geçmiş + en kısa ufuk kadar ileri veri
    month_ends = c.groupby(c["Tarih"].dt.to_period("M"))["Tarih"].max().sort_values()
    min_h = min(horizons)
    fold_dates = [d for d in month_ends
                  if (d - data_start).days >= min_history_days
                  and d + pd.DateOffset(months=min_h) <= data_end + pd.Timedelta(days=3)]
    fold_dates = fold_dates[::max(1, int(step_months))]
    if not fold_dates:
        print("[WARN] Backtest: yeterli geçmiş/ileri veri yok — kat kurulamadı.")
        return None

    rows, weight_hist = [], []
    for t in fold_dates:
        hist = c[c["Tarih"] <= t]
        # Kat başına metrik/skor INFO çıktısı gürültü olur — her durumda sustur;
        # ilerleme bilgisi aşağıdaki tek satırla verilir.
        with contextlib.redirect_stdout(io.StringIO()):
            met = metrics.compute_metrics(hist, risk_free_rate)
            scored = scoring.score_funds(met, None, risk_free_rate) if not met.empty else met
        if scored is None or scored.empty:
            continue
        elig = scored[scored["Uygun"]] if "Uygun" in scored.columns else scored
        portfolio = _build_portfolio(elig, exclude_young=False)
        if not portfolio:
            continue
        weights = {p["Fon Kodu"]: p["Agirlik"] / 100.0 for p in portfolio}
        weight_hist.append(weights)
        universe = scored["Fon Kodu"].tolist()

        for h in horizons:
            end = t + pd.DateOffset(months=h)
            if end > data_end + pd.Timedelta(days=3):
                continue
            end = min(end, data_end)

            # Portföy ileri getirisi (ölçülebilen fonlar üzerinden yeniden normalize)
            fr = {code: _forward_return(series[code], t, end)
                  for code in weights if code in series}
            valid = {k: v for k, v in fr.items() if pd.notna(v)}
            if not valid:
                continue
            wsum = sum(weights[k] for k in valid)
            port_ret = sum(weights[k] * valid[k] for k in valid) / wsum if wsum > 0 else np.nan

            # Evren (aynı katta skorlanabilen fonlar) ileri getirisi
            uni = np.array([_forward_return(series[code], t, end)
                            for code in universe if code in series])
            uni = uni[~np.isnan(uni)]
            if uni.size < 2:
                continue
            ew, med = float(uni.mean()), float(np.median(uni))
            rows.append({"Tarih": t.date(), "Ufuk_Ay": h,
                         "Portfoy_Getiri": round(port_ret, 4),
                         "Evren_Ort": round(ew, 4), "Evren_Medyan": round(med, 4),
                         "Fark": round(port_ret - ew, 4),
                         "Portfoy_N": len(valid), "Evren_N": int(uni.size)})
        if verbose:
            print(f"[INFO] Kat {t.date()}: {len(portfolio)} fonluk portföy, "
                  f"{len(universe)} fonluk evren.")

    if not rows:
        print("[WARN] Backtest: hiçbir katta ileri getiri ölçülemedi.")
        return None

    folds = pd.DataFrame(rows)
    summary = (folds.groupby("Ufuk_Ay")
               .agg(Kat_Sayisi=("Fark", "size"),
                    Portfoy_Ort=("Portfoy_Getiri", "mean"),
                    Evren_Ort=("Evren_Ort", "mean"),
                    Ort_Fark=("Fark", "mean"),
                    Medyan_Fark=("Fark", "median"),
                    Isabet_Orani=("Fark", lambda s: float((s > 0).mean())))
               .round(4).reset_index())
    tos = [_turnover(a, b) for a, b in zip(weight_hist, weight_hist[1:])]
    avg_to = float(np.mean(tos)) if tos else 0.0
    return BacktestResult(folds=folds, summary=summary, avg_turnover=avg_to)


def print_summary(result: BacktestResult, risk_free_rate: float) -> None:
    """Konsola okunur özet basar."""
    print("\n" + "=" * 64)
    print("WALK-FORWARD DOĞRULAMA ÖZETİ")
    print("=" * 64)
    print(result.summary.to_string(index=False))
    print(f"\nOrtalama aylık portföy devri (turnover): {result.avg_turnover:.1%}")
    for _, r in result.summary.iterrows():
        tag = ("skor sinyali POZİTİF görünüyor" if r["Isabet_Orani"] >= 0.5 and r["Ort_Fark"] > 0
               else "skor sinyali bu dönemde evreni AŞAMADI")
        print(f"  Ufuk {int(r['Ufuk_Ay'])} ay: {int(r['Kat_Sayisi'])} kat, "
              f"ort. fark {r['Ort_Fark']:+.2f} puan, isabet {r['Isabet_Orani']:.0%} → {tag}")
    print("\nNOT: Kat sayısı az; bu bir istatistiksel kanıt değil, yön sağlamasıdır. "
          "Skor/profil ağırlığı değişiklikleri bu doğrulamadan geçirilmelidir.")

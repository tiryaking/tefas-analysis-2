"""
Portföy kurulumu ve tahsis mantığı (report.py'den ayrıldı).

Asıl yatırım-öneri mantığı — örnek portföyün nasıl seçildiği, beklenen
getiri/vol bandı ve yeni-fırsat taraması — PDF yerleşiminden bağımsız, saf ve
test edilebilir fonksiyonlar olarak burada yaşar. report.py yalnızca çizer;
dashboard ve `tefas holdings check` (rebalans) aynı fonksiyonları kullanır.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, scoring
from .themes import fund_theme


def build_portfolio(df: pd.DataFrame, *, theme_cap: int = 1,
                    fill: bool = True) -> list[dict]:
    """Profil skorlarından örnek çok-profilli portföy kurar.

    `theme_cap`: bir temadan portföye girebilecek azami fon sayısı.
    Varsayılan 1 (katı tema tekliği) — walk-forward doğrulamasıyla seçildi
    (2026-07-08, YAT/rf=65, 13 kat): cap=1 isabet %69 @1ay / %82 @3ay;
    cap=2 → %62/%64; slotların %50'si (eski soft cap) → %46/%55. Tema
    çeşitliliği sinyalin taşıyıcısı; tavan gevşedikçe monoton bozuluyor.

    `fill=True` dar (filtrelenmiş) evrenlerde boş kalan profil slotlarını tema
    kısıtına bakmadan en iyi kalan fonlarla doldurur — geniş evrende hiç
    devreye girmez (backtest'te fill'li/fill'siz kat sonuçları birebir aynı),
    dar evrende portföyün tek-iki fona çökmesini önler.
    """
    plan = [("Conservative", "Muhafazakâr", 2, 22.0), ("Balanced", "Dengeli", 2, 16.0),
            ("Moderate", "Orta", 1, 14.0), ("Aggressive", "Agresif", 1, 10.0)]
    max_theme_count = max(1, int(theme_cap))
    portfolio, used_codes, theme_counts = [], set(), {}

    def add_row(r, label, weight, score_col):
        code, theme = r["Fon Kodu"], fund_theme(r["Fon Adi"])
        portfolio.append({"Fon Kodu": code, "Fon Adi": r["Fon Adi"], "Profil": label,
                          "Tema": theme, "Agirlik": weight, "Secim_Skoru": r.get(score_col),
                          "Yillik_Getiri": r.get("Yillik_Getiri"),
                          "Yillik_Volatilite": r.get("Yillik_Volatilite"),
                          "Sharpe_Orani": r.get("Sharpe_Orani")})
        used_codes.add(code)
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
    for score_key, label, n_sel, weight in plan:
        col = f"{score_key}_Score"
        if col not in df.columns:
            continue
        picked = 0
        ranked = df.sort_values(col, ascending=False)
        profile_themes = set()
        for _, r in ranked.iterrows():
            if picked >= n_sel:
                break
            code, theme = r["Fon Kodu"], fund_theme(r["Fon Adi"])
            if code in used_codes or theme in profile_themes or theme_counts.get(theme, 0) >= max_theme_count:
                continue
            add_row(r, label, weight, col)
            profile_themes.add(theme)
            picked += 1
        if fill:
            for _, r in ranked.iterrows():
                if picked >= n_sel:
                    break
                if r["Fon Kodu"] in used_codes:
                    continue
                add_row(r, label, weight, col)
                picked += 1
    total = sum(p["Agirlik"] for p in portfolio)
    if total > 0:
        for p in portfolio:
            p["Agirlik"] = p["Agirlik"] / total * 100.0
    return portfolio


def portfolio_expected(portfolio: list[dict]) -> tuple[float, float, float]:
    """Ağırlıklı beklenen getiri + volatilite bandı (korelasyonsuz, tam korele).

    Kovaryans-temelli gerçek portföy volu için `portfolio.portfolio_risk`
    esastır; bu band yalnızca kovaryans hesaplanamadığında gösterilir.
    """
    w = np.array([p["Agirlik"] / 100.0 for p in portfolio])
    r = np.array([p["Yillik_Getiri"] if pd.notna(p["Yillik_Getiri"]) else 0.0 for p in portfolio])
    v = np.array([p["Yillik_Volatilite"] if pd.notna(p["Yillik_Volatilite"]) else 0.0 for p in portfolio])
    return float(np.sum(w * r)), float(np.sqrt(np.sum((w * v) ** 2))), float(np.sum(w * v))


def rebalance(current_weights: dict[str, float], model: list[dict],
              total_value: float, threshold_pts: float = 5.0) -> list[dict]:
    """Gerçek portföyü model portföye taşıyan işlem önerileri.

    `current_weights`: {kod: ağırlık %} (açık pozisyonlardan);
    `model`: `build_portfolio` çıktısı. En büyük mutlak sapma
    `threshold_pts` puanın altındaysa portföy dengede sayılır ve boş liste
    döner; aşıldığında TÜM sıfır-olmayan farklar için TL tutarlı öneriler
    üretilir (alımlar + satımlar ~sıfıra toplanır — rebalans kendi kendini
    finanse eder, yeni nakit gerektirmez).
    """
    model_weights = {str(p["Fon Kodu"]): float(p["Agirlik"]) for p in model}
    all_codes = sorted(set(current_weights) | set(model_weights))
    diffs = {c: model_weights.get(c, 0.0) - float(current_weights.get(c, 0.0))
             for c in all_codes}
    if not diffs or max(abs(d) for d in diffs.values()) < threshold_pts:
        return []
    suggestions = []
    for code in all_codes:
        d = diffs[code]
        if abs(d) < 0.05:   # yuvarlama tozu
            continue
        suggestions.append({
            "Fon Kodu": code,
            "Islem": "AL" if d > 0 else "SAT",
            "Mevcut_Pct": round(float(current_weights.get(code, 0.0)), 1),
            "Hedef_Pct": round(model_weights.get(code, 0.0), 1),
            "Fark_Puan": round(d, 1),
            "Tutar_TL": round(d / 100.0 * total_value, 2),
        })
    return sorted(suggestions, key=lambda s: -abs(s["Fark_Puan"]))


def new_opportunities(df: pd.DataFrame, combined: pd.DataFrame | None,
                      min_months: int = 2, max_months: int = 6) -> pd.DataFrame:
    """Yeni fırsat taraması: verideki ilk fiyat günü (kuruluş vekili) rapor
    referans tarihinden en az `min_months`, en çok `max_months` ay önce olan
    genç fonlar. Bu fonların çoğunda yıllıklandırılmış getiri/Sharpe henüz
    hesaplanamaz (< 63 gözlem NaN döner); bu yüzden Fırsat Skoru kohort-İÇİ
    yüzdelik sıralardan, kısa pencerede anlamlı metriklerle kurulur:
    3A getiri %30, 1A getiri %25, pozitif gün oranı %20, düşük drawdown %15,
    AUM/likidite %10. Veri setinin ilk gününe yapışık başlayan seriler
    (kesik geçmiş — fon aslında daha yaşlı olabilir) elenir.
    """
    if "Fon_Kurulus_Tarihi" not in df.columns:
        return df.iloc[0:0]
    kurulus = pd.to_datetime(df["Fon_Kurulus_Tarihi"], errors="coerce")
    if combined is not None and len(combined):
        dates = pd.to_datetime(combined["Tarih"])
        ref, data_start = dates.max(), dates.min()
    else:
        ref, data_start = pd.Timestamp(datetime.now().date()), None
    mask = (kurulus <= ref - pd.DateOffset(months=min_months)) & \
           (kurulus >= ref - pd.DateOffset(months=max_months))
    if data_start is not None:
        mask &= kurulus > data_start + pd.Timedelta(days=5)
    mask &= pd.to_numeric(df["Veri_Noktasi_Sayisi"], errors="coerce") >= config.MIN_DATA_POINTS
    mask &= pd.to_numeric(df["Getiri_1A"], errors="coerce").notna()
    cohort = df[mask.fillna(False)].copy()
    if cohort.empty:
        return cohort
    cohort["Yas_Ay"] = ((ref - kurulus[cohort.index]).dt.days / 30.44).round(1)
    aum = cohort["Fon_Toplam_Deger_Milyon_TL"] if "Fon_Toplam_Deger_Milyon_TL" in cohort.columns \
        else pd.Series(np.nan, index=cohort.index)
    pr = scoring._pct_rank
    cohort["Firsat_Skoru"] = (
        0.30 * pr(cohort["Getiri_3A"]) +
        0.25 * pr(cohort["Getiri_1A"]) +
        0.20 * pr(cohort["Pozitif_Gun_Orani"]) +
        0.15 * pr(cohort["Max_Drawdown"], ascending=False) +
        0.10 * pr(aum)
    ).round(1)
    return cohort.sort_values("Firsat_Skoru", ascending=False)


def backtest_summary_from_csv(path: Path) -> pd.DataFrame:
    """Walk-forward fold CSV'sinden raporlanabilir ozet uretir."""
    if not path.exists():
        return pd.DataFrame()
    try:
        folds = pd.read_csv(path, encoding=config.OUTPUT_ENCODING)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    required = {"Ufuk_Ay", "Portfoy_Getiri", "Evren_Ort", "Fark"}
    if not required <= set(folds.columns) or folds.empty:
        return pd.DataFrame()
    return (folds.groupby("Ufuk_Ay")
            .agg(Kat_Sayisi=("Fark", "size"),
                 Portfoy_Ort=("Portfoy_Getiri", "mean"),
                 Evren_Ort=("Evren_Ort", "mean"),
                 Ort_Fark=("Fark", "mean"),
                 Medyan_Fark=("Fark", "median"),
                 Isabet_Orani=("Fark", lambda s: float((s > 0).mean())))
            .round(4).reset_index())

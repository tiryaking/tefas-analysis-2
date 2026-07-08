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


PROFILE_PLAN = [
    ("Conservative", "Muhafazakâr", 2, 22.0),
    ("Balanced", "Dengeli", 2, 16.0),
    ("Moderate", "Orta", 1, 14.0),
    ("Aggressive", "Agresif", 1, 10.0),
]


def add_decision_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Skoru değiştirmeden öneri kararında kullanılan açıklayıcı bayrakları ekler.

    AUM burada getiri skoru değildir; likidite/ölçek sinyali olarak etiketlenir.
    Kısa geçmişli fonlar ana öneriye sokulmaz, izleme listesi adayı olur. Rf altı
    düşük oynaklıklı fonlar ayrıca işaretlenir: bu fonlar düşük riskli görünse de
    nakit/rf alternatifinin altında kalmış olabilir.
    """
    out = df.copy()
    idx = out.index
    data_points = pd.to_numeric(out.get("Veri_Noktasi_Sayisi"), errors="coerce") \
        if "Veri_Noktasi_Sayisi" in out.columns else pd.Series(np.nan, index=idx)
    age = pd.to_numeric(out.get("Fon_Yasi_Yil"), errors="coerce") \
        if "Fon_Yasi_Yil" in out.columns else pd.Series(np.nan, index=idx)
    aum = pd.to_numeric(out.get("Fon_Toplam_Deger_Milyon_TL"), errors="coerce") \
        if "Fon_Toplam_Deger_Milyon_TL" in out.columns else pd.Series(np.nan, index=idx)
    vol = pd.to_numeric(out.get("Yillik_Volatilite"), errors="coerce") \
        if "Yillik_Volatilite" in out.columns else pd.Series(np.nan, index=idx)
    drawdown = pd.to_numeric(out.get("Max_Drawdown"), errors="coerce") \
        if "Max_Drawdown" in out.columns else pd.Series(np.nan, index=idx)
    rf_ustu = out["Rf_Ustu"].fillna(False).astype(bool) if "Rf_Ustu" in out.columns \
        else pd.Series(True, index=idx)

    out["Kisa_Gecmis"] = (
        (data_points.notna() & (data_points < config.TRADING_DAYS_PER_YEAR)) |
        (age.notna() & (age < 1.0))
    ).astype(bool)
    out["Dusuk_AUM"] = (aum.notna() & (aum < config.AUM_BONUS_THRESHOLD)).astype(bool)
    high_dd_cutoff = drawdown.quantile(0.75) if drawdown.notna().sum() >= 4 else drawdown.median()
    out["Yuksek_Drawdown"] = (
        drawdown.notna() & pd.notna(high_dd_cutoff) & (drawdown >= float(high_dd_cutoff)) & (drawdown >= 10.0)
    ).astype(bool)
    out["Likidite_Sinyali"] = np.select(
        [aum.isna(), out["Dusuk_AUM"]],
        ["bilinmiyor", "dusuk_aum"],
        default="olcek_yeterli",
    )

    low_vol_cutoff = vol.quantile(0.25) if vol.notna().sum() >= 4 else vol.median()
    out["Dusuk_Vol_Rf_Alti"] = (
        vol.notna() & pd.notna(low_vol_cutoff) & (vol <= float(low_vol_cutoff)) & ~rf_ustu
    ).astype(bool)

    eligible = out["Uygun"].fillna(True).astype(bool) if "Uygun" in out.columns \
        else pd.Series(True, index=idx)
    out["Oneri_Uygun"] = (eligible & ~out["Kisa_Gecmis"]).astype(bool)
    out["Izleme_Listesi_Adayi"] = (eligible & out["Kisa_Gecmis"]).astype(bool)

    flags = []
    for _, r in out.iterrows():
        row_flags = []
        if not bool(r.get("Oneri_Uygun")):
            row_flags.append("uygunluk disi" if not bool(r.get("Izleme_Listesi_Adayi")) else "kisa gecmis")
        if bool(r.get("Dusuk_AUM")):
            row_flags.append("dusuk AUM")
        if bool(r.get("Yuksek_Drawdown")):
            row_flags.append("yuksek drawdown")
        if bool(r.get("Dusuk_Vol_Rf_Alti")):
            row_flags.append("dusuk oynaklik ama rf alti")
        if "Reel_Getiri_1Y" in out.columns and pd.notna(r.get("Reel_Getiri_1Y")):
            row_flags.append("reel pozitif" if float(r["Reel_Getiri_1Y"]) > 0 else "reel negatif")
        if "Rf_Ustu" in out.columns:
            row_flags.append("rf ustu" if bool(r.get("Rf_Ustu")) else "rf alti")
        flags.append("; ".join(row_flags) if row_flags else "temiz")
    out["Karar_Bayraklari"] = flags
    return out


def eligible_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Ana öneriye girebilecek fon evreni: uygunluk + yeterli geçmiş."""
    flagged = add_decision_flags(df)
    return flagged[flagged["Oneri_Uygun"]].copy()


def watchlist_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Kısa geçmiş nedeniyle ana öneri dışı kalan, izlenecek genç fonlar."""
    flagged = add_decision_flags(df)
    score_col = "Overall_Score" if "Overall_Score" in flagged.columns else None
    out = flagged[flagged["Izleme_Listesi_Adayi"]].copy()
    if score_col and score_col in out.columns:
        out = out.sort_values(score_col, ascending=False)
    return out


def profile_ranked(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    """Bir risk profili için önerilebilir evreni profil skoruna göre sıralar."""
    col = f"{profile}_Score"
    universe = eligible_universe(df)
    if col not in universe.columns:
        return universe.iloc[0:0].copy()
    return universe.sort_values(col, ascending=False)


def build_portfolio(df: pd.DataFrame, *, theme_cap: int = 1,
                    fill: bool = True, exclude_young: bool = True) -> list[dict]:
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

    `exclude_young=True` ana öneride 1 yıldan kısa geçmişli fonları dışarıda
    tutar. Walk-forward testleri erken katları ölçebilmek için bunu kapatabilir;
    ürün raporu/dashboard varsayılan olarak genç fonları izleme listesine ayırır.
    """
    df = add_decision_flags(df)
    max_theme_count = max(1, int(theme_cap))
    portfolio, used_codes, theme_counts = [], set(), {}

    def add_row(r, label, weight, score_col):
        code, theme = r["Fon Kodu"], fund_theme(r["Fon Adi"])
        portfolio.append({"Fon Kodu": code, "Fon Adi": r["Fon Adi"], "Profil": label,
                          "Tema": theme, "Agirlik": weight, "Secim_Skoru": r.get(score_col),
                          "Yillik_Getiri": r.get("Yillik_Getiri"),
                          "Yillik_Volatilite": r.get("Yillik_Volatilite"),
                          "Sharpe_Orani": r.get("Sharpe_Orani"),
                          "Rf_Ustu": r.get("Rf_Ustu"),
                          "Reel_Getiri_1Y": r.get("Reel_Getiri_1Y"),
                          "Karar_Bayraklari": r.get("Karar_Bayraklari"),
                          "Likidite_Sinyali": r.get("Likidite_Sinyali")})
        used_codes.add(code)
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
    for score_key, label, n_sel, weight in PROFILE_PLAN:
        col = f"{score_key}_Score"
        if col not in df.columns:
            continue
        picked = 0
        elig_mask = df["Oneri_Uygun"] if exclude_young else (
            df["Uygun"].fillna(True).astype(bool) if "Uygun" in df.columns
            else pd.Series(True, index=df.index)
        )
        ranked = df[elig_mask].sort_values(col, ascending=False)
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
    from .validation import backtest_summary_from_csv as _summary
    return _summary(path)

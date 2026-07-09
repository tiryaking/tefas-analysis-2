"""
Karşılaştırma mantığı — saf, sunumdan bağımsız (report.py'den ayrıldı).

Metrik satır tanımları, en-iyi-fon seçimi, karşılaştırma matrisi, verdict
satırları ve radar normalizasyonu burada yaşar. Hem PDF (report.py) hem de
dashboard karşılaştırma sayfası bunları tüketir — iki yüzey aynı sayıları ve
aynı "en iyi" kararlarını gösterir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .narrative import fmt, pct
from .themes import fund_theme

# metrik satırı: (etiket, (sütun, yön) | None, biçimlendirici)
# yön "high" → büyük daha iyi; "low" → küçük daha iyi; None → kıyaslanmaz.
CMP_METRICS = [
    ("Tema", None, lambda r: fund_theme(r.get("Fon Adi"))),
    ("Yıllık Getiri", ("Yillik_Getiri", "high"), lambda r: pct(r.get("Yillik_Getiri"))),
    ("rf Üzeri Getiri", None, lambda r: "✓" if bool(r.get("Rf_Ustu")) else "—"),
    ("Kuruluş CAGR", ("Yillik_Getiri_Kurulus", "high"), lambda r: pct(r.get("Yillik_Getiri_Kurulus"))),
    ("Volatilite", ("Yillik_Volatilite", "low"), lambda r: pct(r.get("Yillik_Volatilite"))),
    ("Sharpe", ("Sharpe_Orani", "high"), lambda r: fmt(r.get("Sharpe_Orani"), 2)),
    ("Sortino", ("Sortino_Orani", "high"), lambda r: fmt(r.get("Sortino_Orani"), 2)),
    ("Calmar", ("Calmar_Orani", "high"), lambda r: fmt(r.get("Calmar_Orani"), 2)),
    ("Max Drawdown", ("Max_Drawdown", "low"), lambda r: pct(r.get("Max_Drawdown"))),
    ("VaR %95 (gün)", ("VaR_95", "high"), lambda r: pct(r.get("VaR_95"))),
    ("CVaR %95 (gün)", ("CVaR_95", "high"), lambda r: pct(r.get("CVaR_95"))),
    ("Pozitif Gün %", ("Pozitif_Gun_Orani", "high"), lambda r: pct(r.get("Pozitif_Gun_Orani"))),
    ("Pozitif Ay %", ("Pozitif_Ay_Orani", "high"), lambda r: pct(r.get("Pozitif_Ay_Orani"))),
    ("Reel Getiri", ("Reel_Getiri_1Y", "high"), lambda r: pct(r.get("Reel_Getiri_1Y"))),
    ("AUM (mn TL)", ("Fon_Toplam_Deger_Milyon_TL", "high"), lambda r: fmt(r.get("Fon_Toplam_Deger_Milyon_TL"), 0)),
    ("Fon Yaşı (yıl)", None, lambda r: fmt(r.get("Fon_Yasi_Yil"), 1)),
    ("Veri (gün)", None, lambda r: fmt(r.get("Veri_Noktasi_Sayisi"), 0)),
]

# verdict satırları: (etiket, sütun, yön)
VERDICT_METRICS = [
    ("En yüksek yıllık getiri", "Yillik_Getiri", "high"),
    ("En iyi risk-ayarlı getiri (Sharpe)", "Sharpe_Orani", "high"),
    ("En iyi aşağı-yön koruması (Sortino)", "Sortino_Orani", "high"),
    ("En düşük volatilite", "Yillik_Volatilite", "low"),
    ("En iyi drawdown kontrolü", "Max_Drawdown", "low"),
    ("En yüksek pozitif reel getiri", "Reel_Getiri_1Y", "high"),
    ("En yüksek likidite (AUM)", "Fon_Toplam_Deger_Milyon_TL", "high"),
    ("En tutarlı (pozitif gün oranı)", "Pozitif_Gun_Orani", "high"),
]

RADAR_AXES = [
    ("Yıllık Getiri", "Yillik_Getiri", "high"), ("Sharpe", "Sharpe_Orani", "high"),
    ("Sortino", "Sortino_Orani", "high"), ("Düşük Vol.", "Yillik_Volatilite", "low"),
    ("Düşük DD", "Max_Drawdown", "low"), ("Poz. Gün", "Pozitif_Gun_Orani", "high"),
]


def best_index(met: pd.DataFrame, col: str, direction: str) -> int | None:
    """Bir sütunda en iyi fonun DataFrame indeksi (high→max, low→min); hepsi
    NaN ise None."""
    if col not in met.columns:
        return None
    vals = pd.to_numeric(met[col], errors="coerce")
    if not vals.notna().any():
        return None
    return int(vals.idxmax() if direction == "high" else vals.idxmin())


def best_code(met: pd.DataFrame, col: str, direction: str) -> str:
    idx = best_index(met, col, direction)
    return str(met.loc[idx, "Fon Kodu"]) if idx is not None else "—"


def verdict_rows(met: pd.DataFrame) -> list[tuple[str, str]]:
    """(ölçüt etiketi, kazanan fon kodu) çiftleri — 'en iyi' özeti."""
    return [(label, best_code(met, col, d)) for label, col, d in VERDICT_METRICS]


def comparison_matrix(met: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, int | None]]:
    """Biçimlenmiş karşılaştırma matrisi + satır başına en-iyi sütun konumu.

    Dönen tablo: satırlar metrik etiketleri, sütunlar fon kodları (metrikteki
    sırayla). `best_map[satır_no] = en_iyi_sütun_no` (0-tabanlı, fon sıralaması);
    kıyaslanmayan satırlarda None. `met` reset_index'li varsayılır (0..n-1).
    """
    met = met.reset_index(drop=True)
    codes = met["Fon Kodu"].astype(str).tolist()
    data = {}
    best_map: dict[int, int | None] = {}
    for ri, (label, spec, fn) in enumerate(CMP_METRICS):
        data[label] = [fn(r) for _, r in met.iterrows()]
        if spec is None:
            best_map[ri] = None
        else:
            bi = best_index(met, spec[0], spec[1])
            best_map[ri] = codes.index(str(met.loc[bi, "Fon Kodu"])) if bi is not None else None
    # data: {metrik etiketi: [fon0, fon1, ...]} → satır=metrik, sütun=fon
    table = pd.DataFrame(data).T
    table.columns = codes
    return table, best_map


def prep_radar(met: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """Radar için min-maks normalize edilmiş değerler.

    Dönen: (eksen etiketleri, shape=(eksen, fon) dizi; 0–1, 'low' eksenleri
    ters çevrilmiş). Tek değerli/NaN eksen 0.5'e sabitlenir.
    """
    labels = [a[0] for a in RADAR_AXES]
    norm = []
    for _, col, direction in RADAR_AXES:
        vals = pd.to_numeric(met.get(col), errors="coerce").to_numpy(dtype="float64") \
            if col in met.columns else np.full(len(met), np.nan)
        vmin, vmax = np.nanmin(vals) if np.isfinite(vals).any() else np.nan, \
            np.nanmax(vals) if np.isfinite(vals).any() else np.nan
        if not np.isfinite(vmin) or vmax == vmin:
            scaled = np.full(len(vals), 0.5)
        else:
            scaled = (vals - vmin) / (vmax - vmin)
            if direction == "low":
                scaled = 1.0 - scaled
        norm.append(np.nan_to_num(scaled, nan=0.0))
    return labels, np.array(norm)

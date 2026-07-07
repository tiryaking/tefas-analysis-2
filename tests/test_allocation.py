"""
Örnek portföy kurulumunun (allocation.build_portfolio) ve beklenen getiri/vol
hesabının (portfolio_expected) birim testleri — çekirdek öneri mantığı
daha önce yalnızca PDF smoke testiyle dolaylı sınanıyordu.
"""
import numpy as np
import pandas as pd
import pytest

from tefas.allocation import (build_portfolio as _build_portfolio,
                              portfolio_expected as _portfolio_expected)

# Tema anahtar kelimeleri themes.THEMES'ten: her ad farklı temaya düşer.
_NAMES = {
    "AAA": "AAA HISSE SENEDI FONU",          # Hisse Senedi
    "BBB": "BBB ALTIN FONU",                 # Altın & Kıymetli Maden
    "CCC": "CCC PARA PIYASASI FONU",         # Para Piyasası
    "DDD": "DDD TAHVIL BONO FONU",           # Borçlanma Araçları
    "EEE": "EEE TEKNOLOJI FONU",             # Teknoloji
    "FFF": "FFF KATILIM FONU",               # Katılım
    "GGG": "GGG EMTIA FONU",                 # Emtia & Enerji
    "HHH": "HHH KARMA FONU",                 # Karma / Değişken
}


def _scored_frame(codes=None, **score_overrides):
    codes = codes or list(_NAMES)
    n = len(codes)
    df = pd.DataFrame({
        "Fon Kodu": codes,
        "Fon Adi": [_NAMES[c] for c in codes],
        "Yillik_Getiri": np.linspace(30, 70, n),
        "Yillik_Volatilite": np.linspace(5, 25, n),
        "Sharpe_Orani": np.linspace(0.5, 2.0, n),
    })
    # Varsayılan: her profilde farklı fon öne çıksın diye kaydırılmış skorlar
    base = np.linspace(10, 90, n)
    for i, prof in enumerate(["Conservative", "Balanced", "Moderate", "Aggressive"]):
        df[f"{prof}_Score"] = np.roll(base, i * 2)
    for col, vals in score_overrides.items():
        df[col] = vals
    return df


def test_build_portfolio_basic_invariants():
    port = _build_portfolio(_scored_frame())
    assert 1 <= len(port) <= 6
    codes = [p["Fon Kodu"] for p in port]
    themes_ = [p["Tema"] for p in port]
    assert len(codes) == len(set(codes))            # fon tekrarı yok
    assert len(themes_) == len(set(themes_))        # tema tekrarı yok
    assert sum(p["Agirlik"] for p in port) == pytest.approx(100.0)


def test_build_portfolio_picks_top_scores_first():
    df = _scored_frame()
    df["Conservative_Score"] = [95, 90, 10, 10, 10, 10, 10, 10]  # AAA, BBB en iyi
    port = _build_portfolio(df)
    cons = [p for p in port if p["Profil"].startswith("Muhafazak")]
    assert [p["Fon Kodu"] for p in cons] == ["AAA", "BBB"]
    # Muhafazakâr dilim (2 × 22) toplamın %44'ü olmalı (tam 6 fon seçildiyse)
    if len(port) == 6:
        assert sum(p["Agirlik"] for p in cons) == pytest.approx(44.0)


def test_build_portfolio_theme_dedup():
    """Aynı temadaki iki yüksek skorlu fondan yalnızca biri seçilir."""
    df = _scored_frame()
    df.loc[df["Fon Kodu"] == "BBB", "Fon Adi"] = "BBB HISSE FONU"  # AAA ile aynı tema
    df["Conservative_Score"] = [95, 94, 50, 40, 30, 20, 10, 5]
    port = _build_portfolio(df)
    cons_codes = [p["Fon Kodu"] for p in port if p["Profil"].startswith("Muhafazak")]
    assert cons_codes[0] == "AAA"
    assert "BBB" not in cons_codes                   # tema çakışması → atlandı
    assert max(pd.Series([p["Tema"] for p in port]).value_counts()) <= 3


def test_build_portfolio_fills_narrow_theme_universe():
    codes = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    df = _scored_frame(codes)
    df["Fon Adi"] = [
        "AAA HISSE SENEDI FONU", "BBB HISSE SENEDI FONU",
        "CCC HISSE SENEDI FONU", "DDD HISSE SENEDI FONU",
        "EEE KATILIM FONU", "FFF KATILIM FONU",
        "GGG KATILIM FONU", "HHH KATILIM FONU",
    ]
    for col in ["Conservative_Score", "Balanced_Score", "Moderate_Score", "Aggressive_Score"]:
        df[col] = np.linspace(100, 10, len(df))
    port = _build_portfolio(df)
    assert len(port) == 6
    assert len({p["Tema"] for p in port}) == 2
    assert max(pd.Series([p["Tema"] for p in port]).value_counts()) <= 3
    assert sum(p["Agirlik"] for p in port) == pytest.approx(100.0)


def test_build_portfolio_missing_profile_renormalizes():
    """Eksik skor sütunu (kısmi tablo) profili atlar; ağırlıklar yine 100'e ölçeklenir."""
    df = _scored_frame().drop(columns=["Aggressive_Score"])
    port = _build_portfolio(df)
    assert all(p["Profil"] != "Agresif" for p in port)
    assert sum(p["Agirlik"] for p in port) == pytest.approx(100.0)


def test_build_portfolio_empty():
    assert _build_portfolio(_scored_frame().iloc[0:0]) == []


def test_portfolio_expected_golden():
    port = [
        {"Fon Kodu": "A", "Agirlik": 50.0, "Yillik_Getiri": 10.0, "Yillik_Volatilite": 10.0},
        {"Fon Kodu": "B", "Agirlik": 50.0, "Yillik_Getiri": 20.0, "Yillik_Volatilite": 20.0},
    ]
    exp_ret, vol_lo, vol_hi = _portfolio_expected(port)
    assert exp_ret == pytest.approx(15.0)                       # ağırlıklı getiri
    assert vol_lo == pytest.approx(np.sqrt(5**2 + 10**2))       # korelasyonsuz alt sınır
    assert vol_hi == pytest.approx(15.0)                        # tam korele üst sınır
    assert vol_lo <= vol_hi


def test_portfolio_expected_nan_treated_as_zero():
    port = [{"Fon Kodu": "A", "Agirlik": 100.0,
             "Yillik_Getiri": np.nan, "Yillik_Volatilite": np.nan}]
    exp_ret, vol_lo, vol_hi = _portfolio_expected(port)
    assert exp_ret == 0.0 and vol_lo == 0.0 and vol_hi == 0.0

"""tefas.themes — tema sınıflandırması ve akran (peer) istatistikleri."""
import numpy as np
import pandas as pd
import pytest

from tefas import themes


def test_fund_theme_goldens():
    assert themes.fund_theme("ABC PORTFÖY ALTIN FONU") == "Altın & Kıymetli Maden"
    assert themes.fund_theme("XYZ HİSSE SENEDİ FONU") == "Hisse Senedi"
    assert themes.fund_theme("QQQ PARA PİYASASI FONU") == "Para Piyasası"
    assert themes.fund_theme("TEKNOLOJİ FONU") == "Teknoloji"
    assert themes.fund_theme("TANIMSIZ BİR AD") == "Diğer"
    assert themes.fund_theme(np.nan) == "Diğer"


def test_add_theme():
    df = pd.DataFrame({"Fon Adi": ["A ALTIN FONU", "B HİSSE FONU", None]})
    out = themes.add_theme(df)
    assert list(out["Tema"]) == ["Altın & Kıymetli Maden", "Hisse Senedi", "Diğer"]
    assert "Tema" not in df.columns   # orijinal df değişmez


def _peer_df():
    # 6 fonluk büyük tema + 3 fonluk küçük tema
    rows = [{"Tema": "Büyük", "Yillik_Getiri": v} for v in [10, 20, 30, 40, 50, 60]]
    rows += [{"Tema": "Küçük", "Yillik_Getiri": v} for v in [5, 15, 25]]
    return pd.DataFrame(rows)


def test_theme_relative_percentile_small_theme_nan():
    df = _peer_df()
    out = themes.theme_relative_percentile(df, min_funds=5)
    assert out[df["Tema"] == "Küçük"].isna().all()      # küçük tema -> NaN
    big = out[df["Tema"] == "Büyük"]
    assert big.notna().all()


def test_theme_relative_percentile_monotone():
    df = _peer_df()
    out = themes.theme_relative_percentile(df, min_funds=5)
    big = df[df["Tema"] == "Büyük"].assign(pct=out)
    ordered = big.sort_values("Yillik_Getiri")["pct"].to_numpy()
    assert (np.diff(ordered) > 0).all()                 # getiri arttıkça yüzdelik artar
    assert ordered.max() == pytest.approx(100.0)


def test_theme_medians_excludes_small():
    df = _peer_df()
    med = themes.theme_medians(df, ["Yillik_Getiri"], min_funds=5)
    assert "Büyük" in med.index and "Küçük" not in med.index
    assert med.loc["Büyük", "Yillik_Getiri"] == pytest.approx(35.0)
    assert med.loc["Büyük", "Fon_Sayisi"] == 6


def test_theme_median_growth_path():
    rng = pd.date_range("2025-01-01", periods=50, freq="B")
    rows = []
    for code, drift in [("A", 1.001), ("B", 1.002), ("C", 1.003)]:
        price = 100.0
        for d in rng:
            price *= drift
            rows.append({"Fon Kodu": code, "Tarih": d, "Fiyat": price})
    path = themes.theme_median_growth(pd.DataFrame(rows), min_funds=3)
    assert path is not None
    assert path.iloc[0] == pytest.approx(100.0)
    # medyan günlük getiri %0.2 -> patika ~100 * 1.002^(n-1) civarı bileşiklenir
    assert path.iloc[-1] == pytest.approx(100.0 * 1.002 ** (len(rng) - 1), rel=1e-6)


def test_theme_median_growth_insufficient():
    assert themes.theme_median_growth(pd.DataFrame(columns=["Fon Kodu", "Tarih", "Fiyat"])) is None
    assert themes.theme_median_growth(None) is None

import numpy as np
import pandas as pd
import pytest

from tefas.io_utils import parse_turkish_float
from tefas import scoring
from tefas.cli import _parse_filter_file


def test_parse_filter_file():
    text = """
# yorum
[INCLUDE]
# PARA PİYASASI
[EXCLUDE]
ALTIN
GÜMÜŞ
#SERBEST
PARA PİYASASI
"""
    cfg = _parse_filter_file(text)
    assert cfg["include"] is None                         # hepsi yorumlu -> None
    assert cfg["exclude"] == ["ALTIN", "GÜMÜŞ", "PARA PİYASASI"]  # #SERBEST atlanır


def test_parse_turkish_float():
    assert parse_turkish_float("3.244,52") == 3244.52   # virgül ondalık
    assert parse_turkish_float("3,244.52") == 3244.52   # nokta ondalık
    assert parse_turkish_float("3,5") == 3.5
    assert parse_turkish_float("1234.56") == 1234.56
    assert np.isnan(parse_turkish_float(""))
    assert np.isnan(parse_turkish_float(None))


def test_pct_rank_monotonic():
    s = pd.Series([1, 2, 3, 4])
    r = scoring._pct_rank(s, ascending=True)
    assert r.iloc[0] < r.iloc[-1]            # büyük değer -> yüksek skor
    r_desc = scoring._pct_rank(s, ascending=False)
    assert r_desc.iloc[0] > r_desc.iloc[-1]


def test_pct_rank_fills_nan_neutral():
    s = pd.Series([1.0, np.nan, 3.0])
    r = scoring._pct_rank(s)
    assert r.iloc[1] == 50.0                 # NaN -> nötr 50


def test_triangular_peaks_at_center():
    s = pd.Series([0, 50, 100], dtype=float)
    t = scoring._triangular(s, peak=50.0)
    assert t.iloc[1] == 100.0                # tepe
    assert t.iloc[0] == 0.0 and t.iloc[2] == 0.0


def test_consistency_no_double_count():
    """_consistency artık Max_Drawdown/Sortino/Skewness'a bağlı DEĞİL (çifte sayım yok)."""
    df = pd.DataFrame({
        "Pozitif_Gun_Orani": np.linspace(45, 60, 10),
        "Pozitif_Ay_Orani": np.linspace(40, 70, 10),
        "Aylik_Getiri_Std": np.linspace(2, 20, 10),
    })  # Max_Drawdown / Sortino / Skewness bilinçli olarak YOK
    c = scoring._consistency(df)
    assert c.between(0, 100).all()
    assert c.iloc[-1] > c.iloc[0]     # daha çok pozitif gün/ay -> daha yüksek tutarlılık


def test_score_funds_adds_columns():
    """Skorlama metrik tablosuna beklenen skor sütunlarını ekler."""
    df = pd.DataFrame({
        "Fon Kodu": [f"F{i}" for i in range(30)],
        "Fon Adi": [f"FON {i}" for i in range(30)],
        "Veri_Noktasi_Sayisi": [100] * 30,
        "Getiri_1A": np.linspace(1, 10, 30),
        "Getiri_3A": np.linspace(2, 20, 30),
        "Getiri_1Y": np.linspace(40, 90, 30),
        "Yillik_Volatilite": np.linspace(5, 40, 30),
        "Sharpe_Orani": np.linspace(0.1, 3, 30),
        "Sortino_Orani": np.linspace(0.1, 5, 30),
        "Calmar_Orani": np.linspace(0.1, 4, 30),
        "Max_Drawdown": np.linspace(2, 30, 30),
        "Skewness": np.linspace(-1, 1, 30),
        "Pozitif_Gun_Orani": np.linspace(45, 60, 30),
        "Fon_Toplam_Deger_Milyon_TL": np.linspace(10, 500, 30),
        "Yillik_Getiri": np.linspace(40, 90, 30),
        "Skor_Penceresi_Gun": [252] * 30,
    })
    out = scoring.score_funds(df, combined=None, risk_free_rate=45.0)
    for col in ["Overall_Score", "Conservative_Score", "Balanced_Score",
                "Moderate_Score", "Aggressive_Score", "Consistency_Score",
                "Tema", "Yillik_Getiri_Duzeltilmis", "Tema_Rel_Skor"]:
        assert col in out.columns
    assert out["Overall_Score"].between(0, 100).all()
    # Tam pencere (252 >= 189) -> shrinkage yok, düzeltilmiş == ham
    assert np.allclose(out["Yillik_Getiri_Duzeltilmis"], out["Yillik_Getiri"])


def _shrink_df(days_a=64, days_b=252):
    """Aynı getirili iki fon; yalnızca pencere uzunlukları farklı."""
    n = 12
    return pd.DataFrame({
        "Fon Kodu": [f"F{i}" for i in range(n)],
        "Fon Adi": [f"FON {i}" for i in range(n)],   # hepsi 'Diğer' teması
        "Tema": ["Diğer"] * n,
        "Yillik_Getiri": [100.0, 100.0] + [30.0] * (n - 2),   # medyan 30
        "Skor_Penceresi_Gun": [days_a, days_b] + [252] * (n - 2),
    })


def test_shrunk_return_pulls_thin_history():
    df = _shrink_df(days_a=64, days_b=252)
    s = scoring.shrunk_annual_return(df, full_days=189)
    # İnce geçmişli fon (64 gün) medyana (30) doğru çekilir; tam pencereli çekilmez.
    assert s.iloc[1] == 100.0
    assert 30.0 < s.iloc[0] < 100.0
    w = 64 / 189
    assert s.iloc[0] == pytest.approx(w * 100.0 + (1 - w) * 30.0)


def test_shrunk_return_full_credibility():
    df = _shrink_df(days_a=189, days_b=252)
    s = scoring.shrunk_annual_return(df, full_days=189)
    assert s.iloc[0] == 100.0 and s.iloc[1] == 100.0   # >= 189 gün -> değişmez


def test_shrunk_return_missing_window_column():
    df = _shrink_df().drop(columns=["Skor_Penceresi_Gun"])
    s = scoring.shrunk_annual_return(df, full_days=189)
    assert s.iloc[0] == 100.0                          # sütun yok -> w=1, dokunma


def test_small_theme_composite_not_nan():
    """Niş temadaki fonun Tema_Rel_Skor'u NaN ama composite skoru tanımlı kalır."""
    n = 8
    df = pd.DataFrame({
        "Fon Kodu": [f"F{i}" for i in range(n)],
        # 1 fon Altın temasında (tema < 5 fon), kalanlar 'Diğer'
        "Fon Adi": ["X ALTIN FONU"] + [f"FON {i}" for i in range(1, n)],
        "Veri_Noktasi_Sayisi": [100] * n,
        "Getiri_1A": np.linspace(1, 8, n),
        "Getiri_3A": np.linspace(2, 16, n),
        "Yillik_Volatilite": np.linspace(5, 40, n),
        "Sharpe_Orani": np.linspace(0.1, 3, n),
        "Sortino_Orani": np.linspace(0.1, 5, n),
        "Calmar_Orani": np.linspace(0.1, 4, n),
        "Max_Drawdown": np.linspace(2, 30, n),
        "Pozitif_Gun_Orani": np.linspace(45, 60, n),
        "Fon_Toplam_Deger_Milyon_TL": np.linspace(10, 500, n),
        "Yillik_Getiri": np.linspace(40, 90, n),
        "Skor_Penceresi_Gun": [252] * n,
    })
    out = scoring.score_funds(df, combined=None, risk_free_rate=45.0)
    gold = out[out["Tema"] == "Altın & Kıymetli Maden"]
    assert len(gold) == 1
    assert gold["Tema_Rel_Skor"].isna().all()          # küçük tema -> NaN (raporda "—")
    assert gold["Overall_Score"].notna().all()         # composite yine de tanımlı

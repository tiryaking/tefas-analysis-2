import numpy as np
import pandas as pd

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
    })
    out = scoring.score_funds(df, combined=None, risk_free_rate=45.0)
    for col in ["Overall_Score", "Conservative_Score", "Balanced_Score",
                "Moderate_Score", "Aggressive_Score", "Consistency_Score"]:
        assert col in out.columns
    assert out["Overall_Score"].between(0, 100).all()

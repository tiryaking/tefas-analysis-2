"""
Walk-forward doğrulama (backtest) testleri — sentetik, deterministik evrende
katların kurulduğunu, look-ahead olmadığını ve özetin tutarlı olduğunu sınar.
"""
import numpy as np
import pandas as pd
import pytest

from tefas import backtest as bt


def _combined(n_days=250, start="2025-01-01"):
    """4 fon, 4 farklı tema, farklı sabit günlük getirilerle sentetik evren."""
    rng = pd.date_range(start, periods=n_days, freq="B")
    spec = [
        ("HIS", "HIS HISSE SENEDI FONU", 1.0020),
        ("ALT", "ALT ALTIN FONU", 1.0012),
        ("PPF", "PPF PARA PIYASASI FONU", 1.0008),
        ("TAH", "TAH TAHVIL BONO FONU", 1.0004),
    ]
    rows = []
    for code, name, drift in spec:
        price = 100.0
        for d in rng:
            price *= drift
            rows.append({"Fon Kodu": code, "Fon Adi": name, "Tarih": d,
                         "Fiyat": price, "Fon Toplam Deger": 5e8})
    return pd.DataFrame(rows)


def test_price_asof():
    idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    s = pd.Series([10.0, 11.0, 12.0], index=idx)
    assert bt._price_asof(s, pd.Timestamp("2025-01-03")) == 11.0
    assert bt._price_asof(s, pd.Timestamp("2025-01-05")) == 11.0     # hafta sonu → geri git
    assert np.isnan(bt._price_asof(s, pd.Timestamp("2024-12-31")))   # başlangıç öncesi
    assert np.isnan(bt._price_asof(s, pd.Timestamp("2025-03-01")))   # bayat (>10 gün)


def test_turnover():
    a = {"X": 0.5, "Y": 0.5}
    assert bt._turnover(a, a) == pytest.approx(0.0)
    assert bt._turnover(a, {"X": 0.5, "Z": 0.5}) == pytest.approx(0.5)   # Y çıktı, Z girdi
    assert bt._turnover(a, {}) == pytest.approx(0.5)


def test_run_backtest_produces_folds():
    result = bt.run_backtest(_combined(), risk_free_rate=0.0,
                             horizons=(1,), min_history_days=60, verbose=False)
    assert result is not None
    folds = result.folds
    assert len(folds) >= 3                                   # birkaç kat kurulmalı
    assert {"Tarih", "Ufuk_Ay", "Portfoy_Getiri", "Evren_Ort", "Fark"} <= set(folds.columns)
    assert folds["Portfoy_Getiri"].notna().all()
    assert (folds["Evren_N"] >= 2).all()
    # Özet: isabet oranı [0,1], kat sayısı fold satırlarıyla tutarlı
    s = result.summary
    assert (s["Isabet_Orani"].between(0, 1)).all()
    assert int(s["Kat_Sayisi"].sum()) == len(folds)
    assert 0.0 <= result.avg_turnover <= 1.0


def test_run_backtest_no_lookahead_window():
    """Veri, ufku karşılayamayacak kadar kısaysa hiç kat kurulmaz → None."""
    result = bt.run_backtest(_combined(n_days=50), risk_free_rate=0.0,
                             horizons=(3,), min_history_days=45, verbose=False)
    assert result is None


def test_run_backtest_deterministic_universe_beats_nothing():
    """Deterministik yükselen evrende portföy ve evren getirisi pozitiftir
    (getiri işareti sağlaması — sinyal iddiası değil)."""
    result = bt.run_backtest(_combined(), risk_free_rate=0.0,
                             horizons=(1,), min_history_days=60, verbose=False)
    assert (result.folds["Portfoy_Getiri"] > 0).all()
    assert (result.folds["Evren_Ort"] > 0).all()

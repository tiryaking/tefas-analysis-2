"""
Altın-değer testleri: her risk metriği elle hesaplanmış sonuçlara karşı.

Bunlar v1'de eksikti (FINDING #3). Sharpe/Sortino/drawdown/CAGR/volatilite tam
da sessizce yanlış hesaplanabilen fonksiyonlardır; her biri burada bağımsız
doğrulanıyor.
"""
import numpy as np
import pandas as pd
import pytest

from tefas import metrics as m


def test_annualized_volatility():
    # std(ddof=1) of [1,-1,1,-1] = sqrt(4/3); * sqrt(252)
    expected = np.sqrt(4 / 3) * np.sqrt(252)
    assert m.annualized_volatility([1, -1, 1, -1]) == pytest.approx(expected, rel=1e-9)
    assert m.annualized_volatility([5]) is np.nan or np.isnan(m.annualized_volatility([5]))
    assert np.isnan(m.annualized_volatility([0, 0, 0]))   # sıfır std -> NaN


def test_cagr():
    assert m.cagr(100, 200, 252) == pytest.approx(100.0)        # 1 yılda 2x
    assert m.cagr(100, 121, 504) == pytest.approx(10.0)         # 2 yılda %21 -> %10/yıl
    assert np.isnan(m.cagr(100, 110, 10))                       # < min_days
    assert np.isnan(m.cagr(0, 110, 252))                        # geçersiz fiyat
    assert np.isnan(m.cagr(1, 1000, 252))                       # cap (abs >= 500)


def test_max_drawdown():
    assert m.max_drawdown([100, 120, 90, 110]) == pytest.approx(25.0)  # 120 -> 90
    assert m.max_drawdown([100, 101, 102]) == pytest.approx(0.0)       # monoton artış
    assert np.isnan(m.max_drawdown([100]))


def test_sharpe_ratio():
    assert m.sharpe_ratio(50, 20, 10) == pytest.approx(2.0)
    assert np.isnan(m.sharpe_ratio(50, 0, 10))     # sıfır vol
    assert np.isnan(m.sharpe_ratio(np.nan, 20, 10))


def test_sortino_ratio():
    # downside dev of [1,-1,1,-1] vs rf=0: sqrt(mean([0,1,0,1])) * sqrt(252)
    dd = np.sqrt(0.5) * np.sqrt(252)
    assert m.sortino_ratio([1, -1, 1, -1], 50, 0) == pytest.approx(50 / dd, rel=1e-9)
    # downside yok -> annualized_downside ~0 < MIN_DOWNSIDE -> NaN
    assert np.isnan(m.sortino_ratio([1, 1, 1, 1], 50, 0))


def test_calmar_ratio():
    assert m.calmar_ratio(50, 25, 10) == pytest.approx(1.6)
    assert np.isnan(m.calmar_ratio(50, 0.1, 10))   # mdd < MIN_DD
    assert np.isnan(m.calmar_ratio(np.nan, 25, 10))


def test_net_return():
    # gross 70 -> fee -1 = 69; eşik 60; stopaj (69-60)*0.15=1.35; net 67.65
    assert m.net_return(70) == pytest.approx(67.65)
    # eşiğin altında stopaj yok: gross 40 -> 39
    assert m.net_return(40) == pytest.approx(39.0)


def test_real_return():
    assert m.real_return(55, inflation=55) == pytest.approx(0.0)
    assert m.real_return(110, inflation=55) == pytest.approx((2.10 / 1.55 - 1) * 100)


def test_period_return():
    dates = pd.to_datetime(["2025-01-01", "2025-06-01", "2025-07-01"]).to_numpy()
    prices = np.array([100.0, 110.0, 121.0])
    last_ts = pd.Timestamp("2025-07-01")
    assert m.period_return(dates, prices, last_ts, pd.DateOffset(months=1)) == pytest.approx(10.0)


def test_compute_metrics_integration():
    """Sentetik 2-fonlu evrende uçtan uca metrik üretimi."""
    rng = pd.date_range("2025-01-01", periods=120, freq="B")
    rows = []
    for code, drift in [("AAA", 1.002), ("BBB", 1.001)]:
        price = 100.0
        for d in rng:
            price *= drift
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} FON",
                         "Tarih": d, "Fiyat": price, "Fon Toplam Deger": 5e8})
    combined = pd.DataFrame(rows)
    out = m.compute_metrics(combined, risk_free_rate=0.0)
    assert set(out["Fon Kodu"]) == {"AAA", "BBB"}
    assert {"Sharpe_Orani", "Yillik_Getiri", "Max_Drawdown"} <= set(out.columns)
    # Yükselen seri: pozitif yıllık getiri, drawdown ~0
    assert (out["Yillik_Getiri"] > 0).all()
    assert (out["Max_Drawdown"].fillna(0) < 1).all()

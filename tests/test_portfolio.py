"""
Kovaryans-temelli portföy riski için altın-değer testleri (FINDING #4).

İki sınır durumu elle doğrulanır:
- Tam korele iki varlık: portföy vol = tekil vol (çeşitlendirme yok).
- Korelasyonsuz iki varlık: portföy vol = sqrt(Σ wᵢ²σᵢ²) (çeşitlendirme var).
"""
import numpy as np
import pandas as pd
import pytest

from tefas import portfolio as pf

TD = 252


def test_perfectly_correlated_no_diversification():
    # İki özdeş seri -> kovaryans = varyans, portföy vol = tekil vol
    a = [1.0, -1.0, 1.0, -1.0]
    df = pd.DataFrame({"A": a, "B": a})
    single_vol = np.sqrt(4 / 3) * np.sqrt(TD)          # std(ddof=1)=sqrt(4/3)
    assert pf.portfolio_volatility_from_returns(df, [0.5, 0.5]) == pytest.approx(single_vol, rel=1e-9)
    assert pf.average_correlation(df) == pytest.approx(1.0)


def test_uncorrelated_diversification():
    a = [1.0, -1.0, 1.0, -1.0]
    b = [1.0, 1.0, -1.0, -1.0]                          # cov(a,b)=0
    df = pd.DataFrame({"A": a, "B": b})
    var_each = 4 / 3
    expected = np.sqrt((0.25 * var_each + 0.25 * var_each) * TD)
    assert pf.portfolio_volatility_from_returns(df, [0.5, 0.5]) == pytest.approx(expected, rel=1e-9)
    assert pf.average_correlation(df) == pytest.approx(0.0, abs=1e-12)


def test_uncorrelated_vol_below_correlated():
    a = [1.0, -1.0, 1.0, -1.0]
    b = [1.0, 1.0, -1.0, -1.0]
    corr_df = pd.DataFrame({"A": a, "B": a})
    uncorr_df = pd.DataFrame({"A": a, "B": b})
    assert (pf.portfolio_volatility_from_returns(uncorr_df, [0.5, 0.5])
            < pf.portfolio_volatility_from_returns(corr_df, [0.5, 0.5]))


def test_returns_matrix_aligns_common_dates():
    dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
    combined = pd.DataFrame({
        "Tarih": list(dates) + list(dates),
        "Fon Kodu": ["AAA"] * 4 + ["BBB"] * 4,
        "Fiyat": [100, 110, 121, 133.1, 50, 55, 60.5, 66.55],
    })
    rets = pf.returns_matrix(combined, ["AAA", "BBB"])
    assert list(rets.columns) == ["AAA", "BBB"]
    assert np.allclose(rets["AAA"].to_numpy(), [10.0, 10.0, 10.0])   # ilk gün pct_change NaN -> düşer


def test_risk_contributions_sum_to_one():
    a = [1.0, -1.0, 1.0, -1.0]
    b = [1.0, 1.0, -1.0, -1.0]
    df = pd.DataFrame({"A": a, "B": b})
    rc = pf.risk_contributions(df, [0.5, 0.5])
    assert rc.sum() == pytest.approx(1.0, rel=1e-9)
    # Eşit vol + korelasyonsuz + eşit ağırlık -> eşit risk katkısı
    assert rc[0] == pytest.approx(0.5) and rc[1] == pytest.approx(0.5)


def test_portfolio_drawdown_shape():
    rng = pd.date_range("2025-01-01", periods=40, freq="B")
    rows = []
    for code in ("AAA", "BBB"):
        price = 100.0
        for i, d in enumerate(rng):
            price *= 1.01 if i % 5 else 0.97      # ara ara düşüş -> drawdown oluşsun
            rows.append({"Tarih": d, "Fon Kodu": code, "Fiyat": price})
    combined = pd.DataFrame(rows)
    portfolio = [{"Fon Kodu": "AAA", "Agirlik": 60.0}, {"Fon Kodu": "BBB", "Agirlik": 40.0}]
    res = pf.portfolio_drawdown(combined, portfolio)
    assert res is not None
    idx, cum, dd = res
    assert len(cum) == len(dd) == len(idx)
    assert (dd >= -1e-9).all()                    # drawdown negatif olmamalı (pozitif % kayıp)


def test_portfolio_risk_summary():
    rng = pd.date_range("2025-01-01", periods=60, freq="B")
    rows = []
    for code, step in [("AAA", 1.01), ("BBB", 1.005), ("CCC", 1.002)]:
        price = 100.0
        for d in rng:
            price *= step
            rows.append({"Tarih": d, "Fon Kodu": code, "Fiyat": price})
    combined = pd.DataFrame(rows)
    portfolio = [{"Fon Kodu": "AAA", "Agirlik": 40.0},
                 {"Fon Kodu": "BBB", "Agirlik": 35.0},
                 {"Fon Kodu": "CCC", "Agirlik": 25.0}]
    res = pf.portfolio_risk(combined, portfolio)
    assert res is not None
    assert res["n_used"] == 3
    assert res["portfolio_vol"] >= 0
    # çeşitlendirme kazancı portföy vol'u ağırlıklı ortalamayı aşamaz
    assert res["portfolio_vol"] <= res["weighted_avg_vol"] + 1e-9

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


def test_returns_matrix_union_keeps_long_window():
    """dropna='all': kısa geçmişli fon uzun fonların penceresini KIRPMAZ."""
    long_rng = pd.date_range("2025-01-01", periods=100, freq="B")
    short_rng = long_rng[-30:]
    rows = [{"Tarih": d, "Fon Kodu": "LONG", "Fiyat": 100 + i} for i, d in enumerate(long_rng)]
    rows += [{"Tarih": d, "Fon Kodu": "SHRT", "Fiyat": 50 + i} for i, d in enumerate(short_rng)]
    combined = pd.DataFrame(rows)
    inter = pf.returns_matrix(combined, ["LONG", "SHRT"])                 # kesişim
    union = pf.returns_matrix(combined, ["LONG", "SHRT"], dropna="all")   # birleşim
    assert len(inter) == 29                     # kısa fonun penceresi
    assert len(union) == 99                     # uzun fonun tüm getirileri korunur
    assert union["LONG"].notna().sum() == 99
    assert union["SHRT"].notna().sum() == 29


def test_shrunk_covariance_matches_raw_when_identical():
    """Özdeş iki seri: sabit-korelasyon hedefi = ham matris → büzülme etkisiz."""
    rng = np.random.default_rng(7)
    a = rng.normal(0, 1, 120)
    df = pd.DataFrame({"A": a, "B": a})
    cov, info = pf.shrunk_covariance(df)
    raw = df.cov().to_numpy() * TD
    assert cov == pytest.approx(raw, rel=1e-9)
    assert 0.0 <= info["delta"] <= 1.0
    assert info["t_min"] == 120


def test_shrunk_covariance_short_history_fund():
    """Kısa geçmişli fon eklemek uzun çiftin tahmin penceresini değiştirmez
    ve matris PSD kalır (portföy varyansı >= 0)."""
    rng = np.random.default_rng(11)
    n = 150
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "A": rng.normal(0.1, 1.0, n),
        "B": rng.normal(0.1, 1.2, n),
        "C": np.concatenate([np.full(n - 25, np.nan), rng.normal(0.1, 2.0, 25)]),
    }, index=idx)
    cov, info = pf.shrunk_covariance(df)
    assert cov is not None
    assert info["t_min"] == 25 and info["t_max"] == n
    # A-B çifti kendi 150 gözleminden tahmin edilir (kesişimde 25'e düşerdi)
    ab_raw = df[["A", "B"]].cov().iloc[0, 1] * TD
    # büzülme köşegen-dışını hedefe çeker ama işaret/ölçek makul kalmalı
    assert np.isfinite(cov[0, 1])
    assert abs(cov[0, 1] - ab_raw) < abs(ab_raw) + 5.0
    w = np.array([0.4, 0.4, 0.2])
    assert float(w @ cov @ w) >= 0.0            # PSD


def test_shrunk_covariance_insufficient_overlap():
    df = pd.DataFrame({"A": [1.0, -1.0, 0.5] + [np.nan] * 30,
                       "B": [np.nan] * 30 + [1.0, 0.5, -0.5]})
    cov, info = pf.shrunk_covariance(df)
    assert cov is None and info["t_min"] < pf.MIN_PAIR_OVERLAP


def test_prune_short_overlap_drops_thin_fund():
    n = 100
    df = pd.DataFrame({
        "A": np.random.default_rng(1).normal(size=n),
        "B": np.random.default_rng(2).normal(size=n),
        "C": np.concatenate([np.full(n - 5, np.nan), np.ones(5)]),   # 5 gözlem
    })
    pruned = pf._prune_short_overlap(df)
    assert list(pruned.columns) == ["A", "B"]


def test_portfolio_risk_reports_effective_window():
    rng = pd.date_range("2025-01-01", periods=120, freq="B")
    gen = np.random.default_rng(42)
    rows = []
    for code, scale in [("AAA", 0.5), ("BBB", 1.0), ("CCC", 1.5)]:
        price = 100.0
        for d in rng:
            price *= 1.0 + gen.normal(0.0005, 0.01) * scale
            rows.append({"Tarih": d, "Fon Kodu": code, "Fiyat": price})
    combined = pd.DataFrame(rows)
    portfolio = [{"Fon Kodu": "AAA", "Agirlik": 40.0},
                 {"Fon Kodu": "BBB", "Agirlik": 35.0},
                 {"Fon Kodu": "CCC", "Agirlik": 25.0}]
    res = pf.portfolio_risk(combined, portfolio)
    assert res is not None
    assert res["effective_days"] == 119
    assert 0.0 <= res["shrinkage"] <= 1.0
    assert res["dropped_codes"] == []
    assert res["portfolio_vol"] >= 0


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

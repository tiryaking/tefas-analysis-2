import numpy as np

from tefas import data_quality as dq


def test_screen_ok():
    prices = [100 * (1.005 ** i) for i in range(40)]   # düzgün artış
    res = dq.screen_price_series(prices, min_points=20)
    assert res["quality"] == dq.QUALITY_OK


def test_screen_suspect_jump():
    prices = [100.0] * 25 + [200.0]                     # %100 tek-günlük sıçrama
    res = dq.screen_price_series(prices, min_points=2)
    assert res["quality"] == dq.QUALITY_SUSPECT
    assert res["max_daily_move"] >= 35


def test_screen_insufficient():
    res = dq.screen_price_series([100, 101], min_points=20)
    assert res["quality"] == dq.QUALITY_INSUFFICIENT


def test_clean_daily_returns_clips():
    out = dq.clean_daily_returns([50, -50, 10], clip=25)
    assert list(out) == [25.0, -25.0, 10.0]


def test_daily_returns_pct():
    out = dq.daily_returns_pct([100, 110, 121])
    assert np.allclose(out, [10.0, 10.0])

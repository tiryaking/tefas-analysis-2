"""
Benchmark katmanı testleri: seri okuma, Beta/Alpha/TE/IR altın değerleri ve
metrik tablosuna ekleme (tema eşlemesi + veri yokken NaN garantisi).
"""
import numpy as np
import pandas as pd
import pytest

from tefas import benchmarks as bm

N = 150  # > MIN_RELATIVE_OBS


def _idx(n=N):
    return pd.date_range("2025-01-01", periods=n, freq="B")


def _series_from_returns(returns_pct, start=100.0, idx=None):
    idx = _idx(len(returns_pct) + 1) if idx is None else idx
    prices = start * np.cumprod(np.concatenate([[1.0], 1 + np.asarray(returns_pct) / 100.0]))
    return pd.Series(prices, index=idx)


def test_relative_metrics_beta_two_leveraged():
    """Fon = benchmark'ın 2 katı günlük getiri → Beta ≈ 2, TE > 0."""
    rng = np.random.default_rng(3)
    b_ret = rng.normal(0.05, 1.0, N)
    bench = _series_from_returns(b_ret)
    fund = _series_from_returns(2.0 * b_ret)
    out = bm.relative_metrics(fund, bench, risk_free_rate=45.0)
    assert out["Beta"] == pytest.approx(2.0, rel=1e-6)
    assert out["Tracking_Error"] > 0
    assert out["Benchmark_Gozlem"] == N


def test_relative_metrics_identical_fund_zero_te():
    """Fon = benchmark → Beta 1, TE ~0, IR NaN (0'a bölme), Alpha ~0."""
    rng = np.random.default_rng(5)
    b_ret = rng.normal(0.05, 1.0, N)
    bench = _series_from_returns(b_ret)
    out = bm.relative_metrics(bench.copy(), bench, risk_free_rate=45.0)
    assert out["Beta"] == pytest.approx(1.0, rel=1e-9)
    assert out["Tracking_Error"] == pytest.approx(0.0, abs=1e-9)
    assert np.isnan(out["Information_Ratio"])
    assert out["Alpha"] == pytest.approx(0.0, abs=1e-6)


def test_relative_metrics_insufficient_overlap():
    rng = np.random.default_rng(9)
    bench = _series_from_returns(rng.normal(0, 1, N))
    fund = bench.iloc[-30:]                                  # 30 ortak gün < 60
    out = bm.relative_metrics(fund, bench, risk_free_rate=45.0)
    assert np.isnan(out["Beta"]) and out["Benchmark_Gozlem"] == 0


def test_load_benchmarks_missing_dir(tmp_path):
    assert bm.load_benchmarks(tmp_path / "yok") == {}


def test_load_benchmarks_reads_csv(tmp_path):
    idx = _idx(80)
    vals = 100 + np.arange(80) * 0.5
    pd.DataFrame({"Tarih": idx.strftime("%Y-%m-%d"), "Deger": vals}).to_csv(
        tmp_path / "xu100.csv", index=False)
    # kolon adları eksik dosya atlanmalı
    pd.DataFrame({"kolon": [1, 2]}).to_csv(tmp_path / "bozuk.csv", index=False)
    out = bm.load_benchmarks(tmp_path)
    assert set(out) == {"xu100"}
    assert len(out["xu100"]) == 80
    assert out["xu100"].iloc[0] == pytest.approx(100.0)


def test_add_relative_metrics_theme_mapping():
    """Hisse fonu XU100'e eşlenir; Para Piyasası fonu eşlenmez (NaN kalır)."""
    idx = _idx()
    rng = np.random.default_rng(13)
    b_ret = rng.normal(0.1, 1.0, N - 1)
    bench = _series_from_returns(b_ret, idx=idx)
    rows = []
    for code, name, rets in [
        ("HIS", "HIS HISSE SENEDI FONU", 1.5 * b_ret),
        ("PPF", "PPF PARA PIYASASI FONU", np.full(N - 1, 0.15)),
    ]:
        prices = _series_from_returns(rets, idx=idx)
        rows += [{"Fon Kodu": code, "Fon Adi": name, "Tarih": d, "Fiyat": p}
                 for d, p in prices.items()]
    combined = pd.DataFrame(rows)
    met = pd.DataFrame({"Fon Kodu": ["HIS", "PPF"],
                        "Fon Adi": ["HIS HISSE SENEDI FONU", "PPF PARA PIYASASI FONU"]})
    out = bm.add_relative_metrics(met, combined, {"xu100": bench}, risk_free_rate=45.0)
    his = out[out["Fon Kodu"] == "HIS"].iloc[0]
    ppf = out[out["Fon Kodu"] == "PPF"].iloc[0]
    assert his["Benchmark"] == "xu100"
    assert his["Beta"] == pytest.approx(1.5, rel=1e-6)
    assert pd.isna(ppf["Beta"]) and pd.isna(ppf["Benchmark"])


def test_add_relative_metrics_no_benchmarks_adds_nan_columns():
    met = pd.DataFrame({"Fon Kodu": ["X"], "Fon Adi": ["X HISSE FONU"]})
    combined = pd.DataFrame({"Fon Kodu": ["X"], "Fon Adi": ["X HISSE FONU"],
                             "Tarih": [pd.Timestamp("2025-01-01")], "Fiyat": [100.0]})
    out = bm.add_relative_metrics(met, combined, {}, risk_free_rate=45.0)
    for c in ("Benchmark", "Beta", "Alpha", "Tracking_Error", "Information_Ratio"):
        assert c in out.columns
        assert out[c].isna().all()

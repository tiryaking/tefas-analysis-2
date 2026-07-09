"""dashboard/figures.py birim testleri — her builder go.Figure döner ve
boş/None girdide zarifçe (annotation'lı boş figür) davranır. streamlit
gerektirmez; plotly opsiyonel olduğundan yoksa atlanır."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("plotly")
go = pytest.importorskip("plotly.graph_objects")

from tefas.dashboard import figures as F


def _norm_df():
    idx = pd.date_range("2025-01-01", periods=40, freq="B")
    return pd.DataFrame({"AAA": np.linspace(100, 130, 40),
                         "BBB": np.linspace(100, 110, 40)}, index=idx)


def _met():
    return pd.DataFrame({
        "Fon Kodu": ["AAA", "BBB", "CCC"],
        "Fon Adi": ["AAA FONU", "BBB FONU", "CCC FONU"],
        "Yillik_Getiri": [80.0, 40.0, 20.0], "Yillik_Volatilite": [30.0, 12.0, 3.0],
        "Sharpe_Orani": [1.2, 0.8, 2.5], "Sortino_Orani": [1.5, 1.0, 3.0],
        "Max_Drawdown": [20.0, 8.0, 1.0], "Pozitif_Gun_Orani": [55.0, 60.0, 70.0],
        "Getiri_1A": [5, 3, 1], "Getiri_3A": [12, 7, 3],
        "Getiri_6A": [25, 14, 6], "Getiri_1Y": [80, 40, 20],
    })


def test_color_map_stable():
    cm = F.color_map(["AAA", "BBB"])
    assert cm["AAA"] != cm["BBB"]
    assert F.color_map(["AAA"])["AAA"] == cm["AAA"]   # sıra bazlı, tutarlı


def test_fig_growth_and_empty():
    assert isinstance(F.fig_growth(_norm_df()), go.Figure)
    assert isinstance(F.fig_growth(None), go.Figure)          # boş → annotation figürü
    assert isinstance(F.fig_growth(pd.DataFrame()), go.Figure)


def test_fig_underwater():
    idx = pd.date_range("2025-01-01", periods=30)
    cum = np.linspace(100, 108, 30)
    dd = np.abs(np.sin(np.linspace(0, 3, 30))) * 5
    assert isinstance(F.fig_underwater(idx, cum, dd), go.Figure)


def test_fig_drawdown_lines():
    piv = _norm_df()
    assert isinstance(F.fig_drawdown_lines(piv, ["AAA", "BBB"]), go.Figure)
    assert isinstance(F.fig_drawdown_lines(piv, ["YOK"]), go.Figure)


def test_fig_rolling():
    idx = pd.date_range("2025-01-01", periods=40, freq="B")
    rr = pd.DataFrame({"AAA": np.linspace(10, 40, 40)}, index=idx)
    rv = pd.DataFrame({"AAA": np.linspace(5, 15, 40)}, index=idx)
    assert isinstance(F.fig_rolling(rr, rv, rf=65), go.Figure)
    assert isinstance(F.fig_rolling(None, None), go.Figure)


def test_fig_monthly_heatmap():
    idx = pd.period_range("2025-01", periods=6, freq="M")
    monthly = pd.DataFrame({"AAA": [1, -2, 3, -1, 2, 0.5],
                            "BBB": [0.5, 1, -1, 2, -0.5, 1]}, index=idx)
    assert isinstance(F.fig_monthly_heatmap(monthly, ["AAA", "BBB"]), go.Figure)
    assert isinstance(F.fig_monthly_heatmap(pd.DataFrame(), ["AAA"]), go.Figure)


def test_fig_corr_heatmap():
    corr = pd.DataFrame([[1.0, 0.3], [0.3, 1.0]], index=["A", "B"], columns=["A", "B"])
    assert isinstance(F.fig_corr_heatmap(corr), go.Figure)
    assert isinstance(F.fig_corr_heatmap(None), go.Figure)


def test_fig_radar_and_period_bars():
    assert isinstance(F.fig_radar(_met()), go.Figure)
    assert isinstance(F.fig_radar(pd.DataFrame()), go.Figure)
    assert isinstance(F.fig_period_bars(_met()), go.Figure)


def test_fig_weight_vs_risk():
    risk = {"weights": {"AAA": 0.6, "BBB": 0.4},
            "risk_contributions": {"AAA": 0.7, "BBB": 0.3}}
    assert isinstance(F.fig_weight_vs_risk(risk), go.Figure)
    assert isinstance(F.fig_weight_vs_risk(None), go.Figure)

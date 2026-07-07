"""
Rebalans önerileri (allocation.rebalance) ve portföy sinyalleri
(holdings.signals) için birim testler.
"""
import pandas as pd
import pytest

from tefas import holdings as h
from tefas.allocation import rebalance


def _model(weights: dict) -> list[dict]:
    return [{"Fon Kodu": c, "Agirlik": w} for c, w in weights.items()]


# ─── Rebalans ─────────────────────────────────────────────────────────────────

def test_rebalance_below_threshold_no_suggestions():
    cur = {"AAA": 52.0, "BBB": 48.0}
    model = _model({"AAA": 50.0, "BBB": 50.0})
    assert rebalance(cur, model, total_value=100_000) == []


def test_rebalance_suggestions_sum_to_zero():
    cur = {"AAA": 70.0, "BBB": 30.0}
    model = _model({"AAA": 40.0, "BBB": 40.0, "CCC": 20.0})
    sugg = rebalance(cur, model, total_value=100_000)
    assert sugg, "eşik aşıldı, öneri bekleniyordu"
    assert sum(s["Tutar_TL"] for s in sugg) == pytest.approx(0.0, abs=1.0)
    by_code = {s["Fon Kodu"]: s for s in sugg}
    assert by_code["AAA"]["Islem"] == "SAT"
    assert by_code["AAA"]["Tutar_TL"] == pytest.approx(-30_000)
    assert by_code["CCC"]["Islem"] == "AL"
    assert by_code["CCC"]["Tutar_TL"] == pytest.approx(20_000)


def test_rebalance_orders_by_largest_drift():
    cur = {"AAA": 70.0, "BBB": 30.0}
    model = _model({"AAA": 40.0, "BBB": 40.0, "CCC": 20.0})
    sugg = rebalance(cur, model, total_value=1000)
    drifts = [abs(s["Fark_Puan"]) for s in sugg]
    assert drifts == sorted(drifts, reverse=True)


# ─── Sinyaller ────────────────────────────────────────────────────────────────

def _history(rows):
    df = pd.DataFrame(rows, columns=["Tarih", "Fon Kodu", "Overall_Persentil"])
    df["Tarih"] = pd.to_datetime(df["Tarih"])
    return df


_SCORED = pd.DataFrame({"Fon Kodu": ["AAA", "BBB"]})


def test_signals_percentile_drop_flagged():
    hist = _history([
        ("2026-05-31", "AAA", 90.0), ("2026-05-31", "BBB", 50.0),
        ("2026-06-30", "AAA", 70.0), ("2026-06-30", "BBB", 52.0),
    ])
    sigs = h.signals(["AAA", "BBB"], _SCORED, hist)
    aaa = [s for s in sigs if s["Fon Kodu"] == "AAA"]
    # Hem düşüş (90→70, -20 puan) hem üst çeyrek çıkışı (90≥75 → 70<75)
    assert len(aaa) == 2 and all(s["Tip"] == "UYARI" for s in aaa)
    assert not [s for s in sigs if s["Fon Kodu"] == "BBB"]


def test_signals_top_quartile_exit_only():
    hist = _history([
        ("2026-05-31", "AAA", 78.0),
        ("2026-06-30", "AAA", 71.0),   # -7 puan (< 10) ama üst çeyrekten çıktı
    ])
    sigs = h.signals(["AAA"], _SCORED, hist)
    assert len(sigs) == 1
    assert "üst çeyrekten" in sigs[0]["Mesaj"]


def test_signals_missing_from_scored():
    hist = _history([
        ("2026-05-31", "GONE", 60.0),
        ("2026-06-30", "GONE", 60.0),
    ])
    sigs = h.signals(["GONE"], _SCORED, hist)
    assert any("skor tablosunda yok" in s["Mesaj"] for s in sigs)


def test_signals_insufficient_history_is_info_not_error():
    hist = _history([("2026-06-30", "AAA", 80.0)])   # tek snapshot
    sigs = h.signals(["AAA"], _SCORED, hist)
    assert len(sigs) == 1
    assert sigs[0]["Tip"] == "BILGI" and "yetersiz geçmiş" in sigs[0]["Mesaj"]
    # history hiç yoksa da aynı davranış
    sigs = h.signals(["AAA"], _SCORED, None)
    assert sigs and sigs[0]["Tip"] == "BILGI"

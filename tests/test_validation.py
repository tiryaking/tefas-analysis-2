import pandas as pd

from tefas import validation


def test_walk_forward_summary_from_csv(tmp_path):
    p = tmp_path / "bt.csv"
    pd.DataFrame({
        "Tarih": ["2025-01-31", "2025-02-28", "2025-01-31"],
        "Ufuk_Ay": [1, 1, 3],
        "Portfoy_Getiri": [2.0, 1.0, 6.0],
        "Evren_Ort": [1.0, 2.0, 3.0],
        "Fark": [1.0, -1.0, 3.0],
        "Turnover": [0.2, 0.4, 0.6],
    }).to_csv(p, index=False, encoding="utf-8-sig")

    summary = validation.summarize_walk_forward_csv(p)
    one = summary.table[summary.table["Ufuk_Ay"] == 1].iloc[0]

    assert summary.available
    assert summary.status == "ok"
    assert one["Kat_Sayisi"] == 2
    assert one["Ort_Fark"] == 0.0
    assert one["Medyan_Fark"] == 0.0
    assert one["Isabet_Orani"] == 0.5
    assert one["Turnover"] == 0.3


def test_walk_forward_summary_missing_csv_is_controlled(tmp_path):
    summary = validation.summarize_walk_forward_csv(tmp_path / "missing.csv")

    assert not summary.available
    assert summary.status == "missing"
    assert "bulunamadı" in summary.message
    assert summary.table.empty


def test_walk_forward_summary_missing_columns_is_controlled(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"Ufuk_Ay": [1], "Fark": [0.5]}).to_csv(
        p, index=False, encoding="utf-8-sig")

    summary = validation.summarize_walk_forward_csv(p)

    assert not summary.available
    assert summary.status == "invalid"
    assert summary.missing_columns == ("Evren_Ort", "Portfoy_Getiri")

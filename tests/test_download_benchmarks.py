"""
GetDataSet/download_benchmarks.py saf dönüşümleri: EVDS JSON -> satırlar,
mevduat oranından toplam-getiri endeksi sentezi, merge. Ağ erişimi YOK —
canned JSON fixture'larıyla test edilir.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "download_benchmarks",
    Path(__file__).resolve().parents[1] / "GetDataSet" / "download_benchmarks.py")
db = importlib.util.module_from_spec(_SPEC)
sys.modules["download_benchmarks"] = db
_SPEC.loader.exec_module(db)


def test_parse_items_maps_dots_and_skips_nulls():
    items = [
        {"Tarih": "02-01-2025", "TP_DK_USD_S_YTL": "35.42", "UNIXTIME": 1},
        {"Tarih": "03-01-2025", "TP_DK_USD_S_YTL": None},          # tatil -> atla
        {"Tarih": "04-01-2025", "TP_DK_USD_S_YTL": "35,61"},        # Türkçe ondalık
        {"Tarih": "05-01-2025"},                                     # anahtar yok -> atla
    ]
    rows = db.parse_items(items, "TP.DK.USD.S.YTL")
    assert rows == [("2025-01-02", 35.42), ("2025-01-04", 35.61)]


def test_parse_items_empty_or_none():
    assert db.parse_items([], "X.Y") == []
    assert db.parse_items(None, "X.Y") == []


def test_deposit_index_compounds_daily():
    # %36.5 yıllık -> günlük tam 0.001 (36.5/36500). 10 gün sonra 100*(1.001)^10.
    rows = [("2025-01-01", 36.5), ("2025-01-11", 36.5)]
    idx = db.deposit_index(rows)
    assert idx[0] == ("2025-01-01", 100.0)
    assert idx[1][0] == "2025-01-11"
    assert idx[1][1] == pytest.approx(100.0 * 1.001 ** 10, rel=1e-9)


def test_deposit_index_uses_previous_rate_between_observations():
    # İlk 10 gün %36.5, sonraki 10 gün %73 ile bileşir (oran gecikmeli uygulanır).
    rows = [("2025-01-01", 36.5), ("2025-01-11", 73.0), ("2025-01-21", 73.0)]
    idx = db.deposit_index(rows)
    expected_mid = 100.0 * 1.001 ** 10
    expected_end = expected_mid * (1 + 73.0 / 36500.0) ** 10
    # deposit_index çıktıyı 6 haneye yuvarlar
    assert idx[1][1] == pytest.approx(expected_mid, abs=1e-5)
    assert idx[2][1] == pytest.approx(expected_end, abs=1e-5)


def test_merge_rows_new_wins_and_sorted():
    old = [("2025-01-02", 10.0), ("2025-01-03", 11.0)]
    new = [("2025-01-03", 11.5), ("2025-01-04", 12.0)]
    assert db.merge_rows(old, new) == [
        ("2025-01-02", 10.0), ("2025-01-03", 11.5), ("2025-01-04", 12.0)]


def test_csv_roundtrip_atomic(tmp_path):
    p = tmp_path / "xu100.csv"
    rows = [("2025-01-02", 9875.43), ("2025-01-03", 9910.12)]
    db.write_csv_atomic(p, rows)
    assert db.read_csv_rows(p) == rows
    assert not p.with_suffix(".csv.tmp").exists()

"""Karşılaştırma modu testleri: kod ayrıştırma + uçtan uca PDF üretimi."""
import numpy as np
import pandas as pd

from tefas.cli import _parse_comparison_file
from tefas import metrics as m
from tefas import report


def test_parse_comparison_file():
    text = """
# karşılaştırma listesi
[COMPARE]
PRY
pbr          # küçük harf + açıklama
BMU
PRY          # yinelenen -> atlanır
"""
    codes = _parse_comparison_file(text)
    assert codes == ["PRY", "PBR", "BMU"]        # sıra korunur, uppercase, dedup


def test_parse_comparison_from_csv_string():
    # --codes PRY,PBR virgülle -> satıra çevrilerek aynı ayrıştırıcı kullanılır
    assert _parse_comparison_file("PRY,PBR".replace(",", "\n")) == ["PRY", "PBR"]


def _synthetic_combined():
    rng = pd.date_range("2025-01-01", periods=300, freq="B")
    rows = []
    rs = np.random.RandomState(0)
    for code, drift, vol in [("AAA", 1.0018, 0.001), ("BBB", 1.0010, 0.010), ("CCC", 1.0025, 0.030)]:
        price = 100.0
        for d in rng:
            price *= drift * (1.0 + rs.normal(0, vol))
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} PORTFÖY FONU",
                         "Tarih": d, "Fiyat": price, "Fon Toplam Deger": 5e8})
    return pd.DataFrame(rows)


def test_generate_comparison_smoke(tmp_path):
    combined = _synthetic_combined()
    met = m.compute_metrics(combined, risk_free_rate=45.0, keep_suspect=True)
    assert len(met) == 3
    out = report.generate_comparison(met, combined, "YAT", 45.0,
                                     met["Fon Kodu"].tolist(),
                                     out_path=tmp_path / "cmp.pdf")
    assert out.exists() and out.stat().st_size > 5000     # geçerli, boş olmayan PDF

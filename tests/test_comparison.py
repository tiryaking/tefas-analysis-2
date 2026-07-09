"""Karşılaştırma modu testleri: kod ayrıştırma + saf logic + uçtan uca PDF."""
import numpy as np
import pandas as pd
import pytest

from tefas.cli import _parse_comparison_file
from tefas import comparison, metrics as m
from tefas import report, themes


def _cmp_met():
    return pd.DataFrame({
        "Fon Kodu": ["AAA", "BBB", "CCC"],
        "Fon Adi": ["AAA HISSE FONU", "BBB TAHVIL FONU", "CCC PARA PIYASASI FONU"],
        "Yillik_Getiri": [80.0, 40.0, 20.0],
        "Yillik_Volatilite": [30.0, 12.0, 3.0],
        "Sharpe_Orani": [1.2, 0.8, 2.5],
        "Sortino_Orani": [1.5, 1.0, 3.0],
        "Max_Drawdown": [20.0, 8.0, 1.0],
        "Pozitif_Gun_Orani": [55.0, 60.0, 70.0],
        "Reel_Getiri_1Y": [10.0, -2.0, -5.0],
        "Fon_Toplam_Deger_Milyon_TL": [100.0, 800.0, 300.0],
        "Rf_Ustu": [True, False, False],
    })


def test_best_index_high_and_low():
    met = _cmp_met()
    assert comparison.best_index(met, "Yillik_Getiri", "high") == 0   # AAA en yüksek getiri
    assert comparison.best_index(met, "Yillik_Volatilite", "low") == 2  # CCC en düşük vol
    assert comparison.best_index(met, "Yok_Kolon", "high") is None
    all_nan = met.assign(Sharpe_Orani=np.nan)
    assert comparison.best_index(all_nan, "Sharpe_Orani", "high") is None


def test_verdict_rows_pick_winners():
    verdict = dict(comparison.verdict_rows(_cmp_met()))
    assert verdict["En yüksek yıllık getiri"] == "AAA"
    assert verdict["En düşük volatilite"] == "CCC"
    assert verdict["En iyi drawdown kontrolü"] == "CCC"
    assert verdict["En yüksek likidite (AUM)"] == "BBB"


def test_comparison_matrix_shape_and_best_map():
    table, best_map = comparison.comparison_matrix(_cmp_met())
    assert list(table.columns) == ["AAA", "BBB", "CCC"]
    assert table.shape[0] == len(comparison.CMP_METRICS)
    # "Yıllık Getiri" satırı CMP_METRICS'te index 1; en iyi sütun 0 (AAA)
    assert best_map[1] == 0
    # "Tema" satırı (index 0) kıyaslanmaz → None
    assert best_map[0] is None


def test_prep_radar_normalizes_to_unit_range():
    labels, norm = comparison.prep_radar(_cmp_met())
    assert len(labels) == len(comparison.RADAR_AXES)
    assert norm.shape == (len(comparison.RADAR_AXES), 3)
    assert norm.min() >= 0.0 and norm.max() <= 1.0
    # Yıllık Getiri ekseni (axis 0): AAA (en yüksek) → 1.0
    assert norm[0, 0] == pytest.approx(1.0)


def test_prep_radar_constant_axis_is_half():
    met = _cmp_met()
    met["Yillik_Getiri"] = 50.0                  # tüm fonlar eşit
    _, norm = comparison.prep_radar(met)
    assert np.allclose(norm[0], 0.5)


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
    """Evren benchmark'ı verilerek tam yol: büyüme çizgisi, ısı haritası, rolling."""
    combined = _synthetic_combined()
    met = m.compute_metrics(combined, risk_free_rate=45.0, keep_suspect=True)
    assert len(met) == 3
    out = report.generate_comparison(met, combined, "YAT", 45.0,
                                     met["Fon Kodu"].tolist(),
                                     out_path=tmp_path / "cmp.pdf",
                                     universe_growth=themes.theme_median_growth(combined))
    assert out.exists() and out.stat().st_size > 20_000   # yeni sayfalarla dolu PDF


def test_generate_comparison_without_universe_growth(tmp_path):
    """universe_growth verilmezse 'Grup medyanı' fallback'i ile yine üretir."""
    combined = _synthetic_combined()
    met = m.compute_metrics(combined, risk_free_rate=45.0, keep_suspect=True)
    out = report.generate_comparison(met, combined, "YAT", 45.0,
                                     met["Fon Kodu"].tolist(),
                                     out_path=tmp_path / "cmp2.pdf")
    assert out.exists() and out.stat().st_size > 20_000

"""Ana rapor smoke testi: sentetik çok-temalı evrenle uçtan uca PDF üretimi.

Yeni sayfaları (aylık ısı haritası, yuvarlanan metrikler, fon detay sayfaları)
NaN-ay ve küçük-tema yolları dahil çalıştırır. Grafik yardımcılarının kenar
durumlarında None döndürerek zarifçe pes ettiğini de doğrular.
"""
import numpy as np
import pandas as pd

from tefas import metrics as m
from tefas import scoring, report


def _universe(n_days=320, seed=1):
    """~30 fonluk sentetik evren: 2+ tema, bir kısa geçmişli fon, bir niş tema."""
    rng = pd.date_range("2025-01-01", periods=n_days, freq="B")
    rs = np.random.RandomState(seed)
    rows = []
    specs = []
    for i in range(12):
        specs.append((f"HS{i:02d}", f"H{i} HİSSE SENEDİ FONU", 1.0008 + 0.0002 * (i % 5), 0.012))
    for i in range(10):
        specs.append((f"KD{i:02d}", f"K{i} KARMA FON", 1.0009 + 0.0001 * (i % 4), 0.006))
    for i in range(6):
        specs.append((f"TK{i:02d}", f"T{i} TEKNOLOJİ FONU", 1.0012 + 0.0002 * (i % 3), 0.020))
    specs.append(("NIS", "NİŞ SUKUK FONU", 1.0011, 0.004))          # tema < 5 fon
    for code, name, drift, vol in specs:
        price = 100.0
        start = 0
        if code == "HS11":
            start = n_days - 100                                     # kısa geçmişli fon
        for j, d in enumerate(rng):
            if j < start:
                continue
            price *= drift * (1.0 + rs.normal(0, vol))
            rows.append({"Fon Kodu": code, "Fon Adi": name, "Tarih": d,
                         "Fiyat": price, "Fon Toplam Deger": 1e8 * (1 + (j % 7))})
    return pd.DataFrame(rows)


def test_generate_report_smoke(tmp_path):
    combined = _universe()
    met = m.compute_metrics(combined, risk_free_rate=45.0)
    scored = scoring.score_funds(met, combined, 45.0)
    assert {"Tema", "Tema_Rel_Skor", "Yillik_Getiri_Duzeltilmis", "Rf_Ustu"} <= set(scored.columns)
    out = report.generate(scored, met, "YAT", 45.0, combined=combined,
                          out_path=tmp_path / "rapor.pdf",
                          include=None, exclude=["ALTIN"])
    assert out.exists() and out.stat().st_size > 50_000


def test_chart_helpers_graceful_none(tmp_path):
    assert report._chart_monthly_heatmap(None, ["AAA"], tmp_path / "a.png") is None
    assert report._chart_monthly_heatmap(pd.DataFrame(columns=["Fon Kodu", "Tarih", "Fiyat"]),
                                         [], tmp_path / "b.png") is None
    assert report._chart_rolling(None, ["AAA"], tmp_path / "c.png") is None
    assert report._chart_fund_detail(None, "AAA", tmp_path / "d.png") is None
    assert report._chart_monthly_bars(None, "AAA", tmp_path / "e.png") is None


def test_heatmap_single_month_returns_none(tmp_path):
    rng = pd.date_range("2025-01-01", periods=15, freq="B")   # tek ay -> getiri yok
    rows = [{"Fon Kodu": "AAA", "Fon Adi": "AAA FON", "Tarih": d, "Fiyat": 100 + i}
            for i, d in enumerate(rng)]
    assert report._chart_monthly_heatmap(pd.DataFrame(rows), ["AAA"], tmp_path / "hm.png") is None


def test_heatmap_all_positive_months(tmp_path):
    """Tüm aylar pozitifken TwoSlopeNorm vmin<vcenter guard'ı çalışmalı."""
    rng = pd.date_range("2025-01-01", periods=140, freq="B")
    rows = []
    for code in ("AAA", "BBB"):
        price = 100.0
        for d in rng:
            price *= 1.003                                     # hep pozitif
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} FON", "Tarih": d, "Fiyat": price})
    out = report._chart_monthly_heatmap(pd.DataFrame(rows), ["AAA", "BBB"], tmp_path / "hm.png")
    assert out is not None and (tmp_path / "hm.png").exists()

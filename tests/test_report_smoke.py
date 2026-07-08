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


def _newops_frame():
    """_new_opportunities için asgari sütunlu metrik tablosu."""
    return pd.DataFrame({
        "Fon Kodu": ["ESKI", "GENC", "COKGENC", "KESIK", "IYI"],
        "Fon Adi": ["ESKİ FON", "GENÇ FON", "ÇOK GENÇ FON", "KESİK FON", "İYİ FON"],
        # veri 2025-01-01..2025-12-31; ref = 2025-12-31
        "Fon_Kurulus_Tarihi": ["2025-03-01",   # 10 ay: çok eski
                               "2025-09-01",   # 4 ay: kohortta
                               "2025-12-10",   # <1 ay: çok genç
                               "2025-01-01",   # veri başlangıcına yapışık: elenir
                               "2025-08-15"],  # 4.5 ay: kohortta
        "Veri_Noktasi_Sayisi": [250, 85, 15, 250, 95],
        "Getiri_1A": [2.0, 1.0, 1.5, 2.0, 3.0],
        "Getiri_3A": [6.0, 4.0, np.nan, 6.0, 9.0],
        "Pozitif_Gun_Orani": [60.0, 55.0, 50.0, 60.0, 70.0],
        "Max_Drawdown": [5.0, 8.0, 2.0, 5.0, 3.0],
        "Fon_Toplam_Deger_Milyon_TL": [500.0, 50.0, 10.0, 500.0, 200.0],
    })


def test_new_opportunities_cohort_selection():
    combined = pd.DataFrame({"Tarih": pd.date_range("2025-01-01", "2025-12-31", freq="B")})
    out = report._new_opportunities(_newops_frame(), combined)
    # yalnızca 2–6 ay yaşındakiler; kesik geçmiş ve çok genç/eski fonlar elenir
    assert set(out["Fon Kodu"]) == {"GENC", "IYI"}
    # tüm eksenlerde daha iyi olan fon önde
    assert out.iloc[0]["Fon Kodu"] == "IYI"
    assert "Firsat_Skoru" in out.columns and "Yas_Ay" in out.columns
    assert out["Firsat_Skoru"].between(0, 100).all()


def test_new_opportunities_empty_and_missing_column():
    combined = pd.DataFrame({"Tarih": pd.date_range("2025-01-01", "2025-12-31", freq="B")})
    # sütun yoksa boş döner, patlamaz
    assert report._new_opportunities(pd.DataFrame({"Fon Kodu": ["A"]}), combined).empty
    # veri seti fonun geçmişini kesiyorsa (ilk fiyat = veri başlangıcı) fon
    # yaş penceresine düşse bile elenir — aslında daha yaşlı olabilir
    short = pd.DataFrame({"Tarih": pd.date_range("2025-09-01", "2025-12-31", freq="B")})
    df = _newops_frame()
    df["Fon_Kurulus_Tarihi"] = "2025-09-01"   # ref'e göre 4 ay ama veri başlangıcına yapışık
    assert report._new_opportunities(df, short).empty


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


def test_risk_contribution_chart_created(tmp_path):
    risk = {
        "risk_contributions": {"AAA": 0.25, "BBB": 0.55, "CCC": 0.20},
        "weights": {"AAA": 0.33, "BBB": 0.33, "CCC": 0.34},
    }
    portfolio = [{"Fon Kodu": c} for c in ["AAA", "BBB", "CCC"]]
    out = report._chart_risk_contribution(risk, portfolio, tmp_path / "risk.png")
    assert out is not None and (tmp_path / "risk.png").exists()


def test_backtest_summary_from_csv(tmp_path):
    p = tmp_path / "bt.csv"
    pd.DataFrame({
        "Tarih": ["2025-01-31", "2025-02-28", "2025-01-31"],
        "Ufuk_Ay": [1, 1, 3],
        "Portfoy_Getiri": [2.0, 1.0, 6.0],
        "Evren_Ort": [1.0, 2.0, 3.0],
        "Fark": [1.0, -1.0, 3.0],
    }).to_csv(p, index=False, encoding="utf-8-sig")
    out = report._backtest_summary_from_csv(p)
    one = out[out["Ufuk_Ay"] == 1].iloc[0]
    assert one["Kat_Sayisi"] == 2
    assert one["Ort_Fark"] == 0.0
    assert one["Isabet_Orani"] == 0.5

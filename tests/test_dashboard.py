"""
Dashboard smoke testleri (streamlit.testing.v1.AppTest — headless, tarayıcısız).

streamlit opsiyonel bağımlılıktır; kurulu değilse bu dosya atlanır ve çekirdek
suite etkilenmez. Sayfalar fixture parquet'lerle (monkeypatch'li OUTPUT_DIR)
istisnasız render olmalı.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tefas import config  # noqa: E402

DASH = Path(__file__).resolve().parents[1] / "tefas" / "dashboard"


def _fixture_output(tmp_path, monkeypatch):
    """Küçük ama sayfaların tükettiği tüm kolonları içeren Output/ fixture'ı."""
    out = tmp_path / "Output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)

    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2026-01-05", periods=80)
    rows = []
    for code, drift in [("AAA", 0.003), ("BBB", 0.001), ("CCC", 0.002)]:
        px = 10 * np.cumprod(1 + drift + rng.normal(0, 0.01, len(dates)))
        for d, p in zip(dates, px):
            rows.append({"Tarih": d, "Fon Kodu": code,
                         "Fon Adi": f"{code} HISSE SENEDI FONU", "Fiyat": p})
    combined = pd.DataFrame(rows)
    combined.to_parquet(out / "combined_tefas_data_yatirim.parquet", index=False)

    scored = pd.DataFrame({
        "Fon Kodu": ["AAA", "BBB", "CCC"],
        "Fon Adi": [f"{c} HISSE SENEDI FONU" for c in ["AAA", "BBB", "CCC"]],
        "Tema": ["Hisse Senedi"] * 3,
        "Overall_Score": [80.0, 40.0, 60.0],
        "Conservative_Score": [70.0, 30.0, 50.0],
        "Balanced_Score": [75.0, 35.0, 55.0],
        "Moderate_Score": [72.0, 33.0, 53.0],
        "Aggressive_Score": [68.0, 31.0, 51.0],
        "Yillik_Getiri": [90.0, 40.0, 60.0],
        "Yillik_Volatilite": [20.0, 10.0, 15.0],
        "Sharpe_Orani": [1.2, 0.5, 0.8],
        "Sortino_Orani": [1.5, 0.6, 1.0],
        "Max_Drawdown": [8.0, 4.0, 6.0],
        "Fon_Toplam_Deger_Milyon_TL": [500.0, 120.0, 250.0],
        "Uygun": [True, True, True],
        "Rf_Ustu": [True, False, False],
        "Veri_Noktasi_Sayisi": [80, 80, 80],
    })
    scored.to_parquet(out / "advanced_portfolio_recommendations_yatirim.parquet", index=False)
    scored.to_parquet(out / "tefas_financial_metrics_yatirim.parquet", index=False)
    return out, combined


def _txn_file(tmp_path, monkeypatch):
    p = tmp_path / "portfolio_transactions.csv"
    p.write_text("Tarih,Fon Kodu,Islem,Adet,Fiyat,Not\n"
                 "2026-01-06,AAA,ALIS,100,10.0,\n"
                 "2026-02-02,BBB,ALIS,50,10.0,\n", encoding="utf-8-sig")
    monkeypatch.setattr(config, "DEFAULT_TRANSACTIONS_PATH", p)
    return p


@pytest.mark.parametrize("page", ["app.py", "pages/1_Fon_Kesif.py",
                                  "pages/2_Fon_Detay.py"])
def test_read_only_pages_render(tmp_path, monkeypatch, page):
    _fixture_output(tmp_path, monkeypatch)
    at = AppTest.from_file(str(DASH / page), default_timeout=30)
    at.run()
    assert not at.exception, f"{page}: {at.exception}"


@pytest.mark.parametrize("page", ["pages/3_Portfoyum.py", "pages/4_Denge_Sinyal.py"])
def test_portfolio_pages_render(tmp_path, monkeypatch, page):
    _fixture_output(tmp_path, monkeypatch)
    _txn_file(tmp_path, monkeypatch)
    at = AppTest.from_file(str(DASH / page), default_timeout=30)
    at.run()
    assert not at.exception, f"{page}: {at.exception}"


def test_app_without_data_shows_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "bos")
    at = AppTest.from_file(str(DASH / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    assert at.warning, "veri yokken uyarı bekleniyordu"

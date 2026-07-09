"""narrative.py birim testleri: biçimlendirme, gerekçe, config'den metodoloji."""
import numpy as np
import pandas as pd

from tefas import narrative, model_config


def test_fmt_handles_nan_none_and_numbers():
    assert narrative.fmt(np.nan) == "—"
    assert narrative.fmt(None) == "—"
    assert narrative.fmt(float("inf")) == "—"
    assert narrative.fmt(1234.5, 1) == "1,234.5"
    assert narrative.fmt(0.25, 2, "%") == "0.25%"


def test_pct_and_short_name():
    assert narrative.pct(12.34) == "12.3%"
    assert narrative.pct(np.nan) == "—"
    assert narrative.short_name("ABC", 10) == "ABC"
    long = narrative.short_name("X" * 60, 10)
    assert len(long) == 10 and long.endswith("…")


def test_build_rationale_strong_fund():
    row = {"Sharpe_Orani": 3.5, "Yillik_Volatilite": 3.0, "Max_Drawdown": 2.0,
           "Yillik_Getiri": 80.0, "Fon_Toplam_Deger_Milyon_TL": 500.0}
    txt = narrative.build_rationale(row)
    assert txt.endswith(".")
    assert txt[0].isupper()
    assert "Sharpe" in txt                      # en güçlü sinyal ilk sırada
    assert txt.count(";") <= 2                   # en çok 3 madde


def test_build_rationale_falls_back_to_balanced():
    txt = narrative.build_rationale({"Sharpe_Orani": np.nan, "Yillik_Volatilite": 20.0,
                                     "Max_Drawdown": 15.0, "Yillik_Getiri": 10.0})
    assert "dengeli genel profil" in txt.lower()


def test_methodology_sections_reflect_config_weights():
    cfg = model_config.current()
    sections = narrative.methodology_sections(cfg)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in sections)
    titles = [t for t, _ in sections]
    assert any("Composite Skor" in t for t in titles)
    body = dict(sections)["Model Sürümü & Denetim"]
    assert cfg.version in body
    # Ağırlık metni Sharpe'ın en yüksek (%25) olduğunu yansıtmalı
    composite = dict(sections)["Composite Skor Ağırlıkları"]
    assert "Sharpe (%25)" in composite

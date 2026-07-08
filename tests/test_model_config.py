import numpy as np
import pandas as pd

from tefas import model_config, scoring, validation


def _metrics_frame(n=8):
    return pd.DataFrame({
        "Fon Kodu": [f"F{i:02d}" for i in range(n)],
        "Fon Adi": [f"F{i:02d} HISSE SENEDI FONU" for i in range(n)],
        "Veri_Noktasi_Sayisi": [100] * n,
        "Skor_Penceresi_Gun": [100] * n,
        "Yillik_Getiri": np.linspace(20, 80, n),
        "Getiri_1A": np.linspace(1, 8, n),
        "Getiri_3A": np.linspace(3, 12, n),
        "Yillik_Volatilite": np.linspace(8, 24, n),
        "Sharpe_Orani": np.linspace(0.2, 2.0, n),
        "Sortino_Orani": np.linspace(0.3, 2.5, n),
        "Calmar_Orani": np.linspace(0.1, 2.0, n),
        "Max_Drawdown": np.linspace(3, 18, n),
        "Pozitif_Gun_Orani": np.linspace(45, 80, n),
        "Pozitif_Ay_Orani": np.linspace(40, 75, n),
        "Aylik_Getiri_Std": np.linspace(5, 1, n),
        "Fon_Toplam_Deger_Milyon_TL": np.linspace(50, 500, n),
    })


def test_default_model_config_loads():
    cfg = model_config.load()
    assert cfg.version == model_config.DEFAULT_MODEL_VERSION
    assert cfg.overall_weights["sharpe"] == 0.25
    assert cfg.recommendation_settings["theme_cap"] == 1


def test_missing_model_config_uses_safe_defaults(tmp_path):
    cfg = model_config.load(tmp_path / "missing.json")
    assert cfg.source == "defaults"
    assert cfg.profile_weights["Aggressive"]["momentum"] == 0.25


def test_score_output_includes_model_version():
    out = scoring.score_funds(_metrics_frame(), risk_free_rate=45.0)
    assert set(out["Model_Version"]) == {model_config.DEFAULT_MODEL_VERSION}


def test_validation_summary_keeps_model_version(tmp_path):
    p = tmp_path / "bt.csv"
    pd.DataFrame({
        "Ufuk_Ay": [1, 1],
        "Portfoy_Getiri": [2.0, 1.0],
        "Evren_Ort": [1.0, 1.5],
        "Fark": [1.0, -0.5],
        "Model_Version": ["m1", "m1"],
    }).to_csv(p, index=False, encoding="utf-8-sig")
    summary = validation.summarize_walk_forward_csv(p)
    assert summary.table.loc[0, "Model_Version"] == "m1"

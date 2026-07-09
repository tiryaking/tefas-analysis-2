"""
Dashboard smoke testleri (streamlit.testing.v1.AppTest — headless, tarayıcısız).

streamlit opsiyonel bağımlılıktır; kurulu değilse bu dosya atlanır ve çekirdek
suite etkilenmez. Altı sayfa da fixture parquet'lerle istisnasız render olmalı.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

st = pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tefas import config  # noqa: E402
from tefas.holdings import SCORE_HISTORY_COLUMNS  # noqa: E402

DASH = Path(__file__).resolve().parents[1] / "tefas" / "dashboard"

# themes.py'nin farklı temalara ayıracağı adlar (theme_cap=1 model portföyü için)
_FUNDS = [
    ("AAA", "AAA HISSE SENEDI FONU"),
    ("BBB", "BBB ALTIN FONU"),
    ("CCC", "CCC PARA PIYASASI FONU"),
    ("DDD", "DDD TAHVIL BONO FONU"),
    ("EEE", "EEE TEKNOLOJI FONU"),
]


def _fixture_output(tmp_path, monkeypatch):
    """Sayfaların tükettiği tüm kolonları içeren zengin Output/ fixture'ı."""
    out = tmp_path / "Output"
    out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", out)

    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2026-01-05", periods=120)
    rows = []
    for i, (code, name) in enumerate(_FUNDS):
        px = 10 * np.cumprod(1 + (0.001 + 0.0004 * i) + rng.normal(0, 0.008 + 0.002 * i, len(dates)))
        for d, p in zip(dates, px):
            rows.append({"Tarih": d, "Fon Kodu": code, "Fon Adi": name, "Fiyat": p})
    combined = pd.DataFrame(rows)
    combined.to_parquet(out / "combined_tefas_data_yatirim.parquet", index=False)

    n = len(_FUNDS)
    scored = pd.DataFrame({
        "Fon Kodu": [c for c, _ in _FUNDS],
        "Fon Adi": [nm for _, nm in _FUNDS],
        "Tema": ["Hisse Senedi", "Altın & Kıymetli Maden", "Para Piyasası",
                 "Borçlanma Araçları", "Teknoloji"],
        "Overall_Score": np.linspace(85, 45, n),
        "Conservative_Score": np.linspace(80, 40, n),
        "Balanced_Score": np.linspace(78, 42, n),
        "Moderate_Score": np.linspace(76, 44, n),
        "Aggressive_Score": np.linspace(70, 50, n),
        "Yillik_Getiri": np.linspace(90, 30, n),
        "Yillik_Volatilite": np.linspace(28, 6, n),
        "Sharpe_Orani": np.linspace(1.4, 0.4, n),
        "Sortino_Orani": np.linspace(1.8, 0.5, n),
        "Calmar_Orani": np.linspace(2.0, 0.3, n),
        "Max_Drawdown": np.linspace(18, 3, n),
        "Uygun": [True] * n,
        "Rf_Ustu": [True, False, False, False, True],
        # ≥252: fonlar "kısa geçmiş" sayılmasın (ana öneri evrenine girsinler)
        "Veri_Noktasi_Sayisi": [300] * n,
        "Model_Version": ["tefas-reco-v2.1.0"] * n,
    })
    scored.to_parquet(out / "advanced_portfolio_recommendations_yatirim.parquet", index=False)

    # Metrik tablosu: skor + zenginleştirme sütunları (metrics_enriched için)
    metrics = scored.copy()
    metrics["VaR_95"] = np.linspace(3.5, 0.8, n)
    metrics["VaR_99"] = np.linspace(5.5, 1.2, n)
    metrics["CVaR_95"] = np.linspace(4.5, 1.0, n)
    metrics["En_Kotu_Gun"] = np.linspace(6.0, 1.5, n)
    metrics["Reel_Getiri_1Y"] = np.linspace(20, -8, n)
    metrics["Getiri_1A"] = np.linspace(6, 1, n)
    metrics["Getiri_3A"] = np.linspace(15, 4, n)
    metrics["Getiri_6A"] = np.linspace(30, 9, n)
    metrics["Getiri_1Y"] = np.linspace(90, 30, n)
    metrics["Pozitif_Gun_Orani"] = np.linspace(58, 48, n)
    metrics["Pozitif_Ay_Orani"] = np.linspace(70, 50, n)
    metrics["Yillik_Getiri_Kurulus"] = np.linspace(85, 28, n)
    metrics["Fon_Toplam_Deger_Milyon_TL"] = np.linspace(600, 40, n)
    metrics["Fon_Yasi_Yil"] = np.linspace(5, 1.5, n)
    metrics["Fon_Kurulus_Tarihi"] = pd.Timestamp("2021-01-01")
    metrics.to_parquet(out / "tefas_financial_metrics_yatirim.parquet", index=False)

    # Skor geçmişi: 2 tarih (trend + detay zaman çizgisi için)
    hist_rows = []
    for date, shift in [("2026-05-31", 0.0), ("2026-06-30", 5.0)]:
        for i, (code, _) in enumerate(_FUNDS):
            base = float(np.linspace(85, 45, n)[i])
            hist_rows.append({
                "Tarih": pd.Timestamp(date), "Fon Kodu": code,
                "Overall_Score": base + shift * (1 if i % 2 else -1),
                "Overall_Persentil": float(np.linspace(90, 30, n)[i]) + shift * (1 if i % 2 else -1),
                "Conservative_Score": base, "Balanced_Score": base,
                "Moderate_Score": base, "Aggressive_Score": base,
            })
    pd.DataFrame(hist_rows)[SCORE_HISTORY_COLUMNS].to_parquet(
        out / "score_history_yatirim.parquet", index=False)

    # Backtest CSV (validation.summarize_walk_forward_csv için)
    pd.DataFrame({
        "Ufuk_Ay": [1, 1, 3, 3], "Portfoy_Getiri": [4.0, 3.5, 11.0, 9.0],
        "Evren_Ort": [3.0, 3.2, 9.0, 8.5], "Fark": [1.0, 0.3, 2.0, 0.5],
    }).to_csv(out / "backtest_walkforward_yatirim.csv", index=False, encoding="utf-8-sig")
    return out, combined


# Router (app.py) + her view dosyası tek tek
ALL_PAGES = ["app.py", "views/ozet.py", "views/fon_kesif.py", "views/fon_detay.py",
             "views/karsilastirma.py", "views/portfoy_risk.py", "views/model.py"]


@pytest.mark.parametrize("page", ALL_PAGES)
def test_pages_render(tmp_path, monkeypatch, page):
    _fixture_output(tmp_path, monkeypatch)
    at = AppTest.from_file(str(DASH / page), default_timeout=60)
    at.run()
    assert not at.exception, f"{page}: {at.exception}"


def test_app_without_data_shows_warning(tmp_path, monkeypatch):
    # Router boş veriyle varsayılan sayfayı (Özet) çalıştırır → uyarı çıkmalı
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "bos")
    at = AppTest.from_file(str(DASH / "views/ozet.py"), default_timeout=30)
    at.run()
    assert not at.exception
    assert at.warning, "veri yokken uyarı bekleniyordu"


def test_detail_preselect_from_table_click(tmp_path, monkeypatch):
    """Bir tabloya tıklama session_state['detay_code'] yazar; Fon Detay o fonu
    ön-seçili açmalı."""
    _fixture_output(tmp_path, monkeypatch)
    at = AppTest.from_file(str(DASH / "views/fon_detay.py"), default_timeout=60)
    at.session_state["detay_code"] = "CCC"
    at.run()
    assert not at.exception
    assert at.selectbox[0].value == "CCC"       # tıklanan fon ön-seçili açıldı


def test_comparison_page_with_two_funds(tmp_path, monkeypatch):
    _fixture_output(tmp_path, monkeypatch)
    at = AppTest.from_file(str(DASH / "views/karsilastirma.py"), default_timeout=60)
    at.run()
    assert not at.exception
    # multiselect varsayılanı model portföyden gelir → en az 2 fon, tablo render olur
    assert at.session_state["cmp_codes"] and len(at.session_state["cmp_codes"]) >= 2


def test_whatif_lab_builds_portfolio(tmp_path, monkeypatch):
    """What-if lab theme_cap=2 ile bellekte portföy kurar (disk model'e dokunmaz)."""
    _fixture_output(tmp_path, monkeypatch)
    from tefas import allocation
    from tefas.dashboard import data

    scored = data.load_scored("YAT")
    universe = data.recommendation_universe(scored)
    wf = allocation.build_portfolio(universe, theme_cap=2, fill=True, exclude_young=True)
    assert wf and len(wf) >= 2


def test_dashboard_decision_helpers(tmp_path, monkeypatch):
    _fixture_output(tmp_path, monkeypatch)
    from tefas.dashboard import data

    scored = data.load_scored("YAT")
    decision = data.enriched_frame("YAT")
    universe = data.recommendation_universe(scored)
    model = data.model_portfolio(scored)
    validation_summary = data.load_validation("YAT")

    assert "Karar_Bayraklari" in decision.columns
    assert "VaR_95" in decision.columns          # metrics_enriched çalıştı
    assert not universe.empty
    assert model
    assert validation_summary.available          # backtest CSV fixture'da var

"""Dashboard veri katmanı: mtime-anahtarlı, önbellekli parquet okuyucular.

`st.cache_data` anahtarına dosyanın mtime'ı girer: yeni bir `tefas run`
parquet'i tazelediğinde dashboard bir sonraki etkileşimde otomatik yeniden
yükler; dosyayı kilitlemez (pandas oku-kapat).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from tefas import allocation, config, validation

FUND_TYPES = {"YAT": "Yatırım", "EMK": "Emeklilik"}


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner="Veri yükleniyor…")
def _read_parquet(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path_str)


def _load(p: Path) -> pd.DataFrame | None:
    if not p.exists():
        return None
    return _read_parquet(str(p), _mtime(p))


def load_scored(fund_type: str = "YAT") -> pd.DataFrame | None:
    return _load(config.paths_for(fund_type).scored_parquet)


def load_metrics(fund_type: str = "YAT") -> pd.DataFrame | None:
    return _load(config.paths_for(fund_type).metrics_parquet)


def load_combined(fund_type: str = "YAT") -> pd.DataFrame | None:
    return _load(config.paths_for(fund_type).combined_parquet)


def load_history(fund_type: str = "YAT") -> pd.DataFrame | None:
    return _load(config.paths_for(fund_type).score_history_parquet)


def load_validation(fund_type: str = "YAT") -> validation.WalkForwardSummary:
    return validation.summarize_walk_forward_csv(config.paths_for(fund_type).backtest_csv)


def prepare_decision_frame(scored: pd.DataFrame) -> pd.DataFrame:
    """Dashboard/PDF ortak karar bayraklarını skor tablosuna ekler."""
    if scored is None or scored.empty:
        return pd.DataFrame()
    return allocation.add_decision_flags(scored)


def recommendation_universe(scored: pd.DataFrame) -> pd.DataFrame:
    """Ana öneri evreni; veri yetersiz fixture'larda kontrollü geri düşer."""
    df = prepare_decision_frame(scored)
    if df.empty:
        return df
    main = df[df["Oneri_Uygun"]].copy() if "Oneri_Uygun" in df.columns else df.copy()
    if not main.empty:
        return main
    elig = df[df["Uygun"].fillna(False)].copy() if "Uygun" in df.columns else df.copy()
    return elig if not elig.empty else df


def model_portfolio(scored: pd.DataFrame) -> list[dict]:
    """Dashboard model portföyü: rapordaki allocation kurallarıyla aynı."""
    universe = recommendation_universe(scored)
    if universe.empty:
        return []
    model = allocation.build_portfolio(universe)
    if not model:
        model = allocation.build_portfolio(universe, exclude_young=False)
    return model


def sidebar_fund_type() -> str:
    """Ortak kenar çubuğu: fon tipi seçimi (sayfalar arası tutarlı)."""
    return st.sidebar.selectbox(
        "Fon tipi", list(FUND_TYPES), format_func=lambda k: f"{FUND_TYPES[k]} ({k})",
        key="fund_type")


def no_data_warning(fund_type: str) -> None:
    st.warning(f"`Output/` altında {FUND_TYPES[fund_type]} verisi yok. "
               "Önce terminalde `tefas run` çalıştırın.")

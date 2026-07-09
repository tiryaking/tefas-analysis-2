"""Dashboard veri katmani: mtime-anahtarli, onbellekli parquet okuyucular.

`st.cache_data` anahtarina dosyanin mtime'i girer: yeni bir `tefas run`
parquet'i tazelediinde dashboard bir sonraki etkileimde otomatik yeniden
yukler; dosyayi kilitlemez (pandas oku-kapat).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from tefas import allocation, charts, config, validation

FUND_TYPES = {"YAT": "Yatirim", "EMK": "Emeklilik"}

# Skor tablosunda olmayıp metrik tablosunda bulunan, sayfaların ihtiyaç duyduğu
# ek sütunlar (report.generate ile aynı merge listesi).
_ENRICH_COLS = ["Fon_Toplam_Deger_Milyon_TL", "Fon_Yasi_Yil", "Fon_Kurulus_Tarihi",
                "VaR_95", "VaR_99", "CVaR_95", "En_Kotu_Gun", "Reel_Getiri_1Y",
                "Calmar_Orani", "Getiri_1A", "Getiri_3A", "Getiri_6A", "Getiri_1Y",
                "Pozitif_Gun_Orani", "Pozitif_Ay_Orani", "Yillik_Getiri_Kurulus",
                "Veri_Kalitesi"]


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner="Veri yukleniyor...")
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


def metrics_enriched(scored: pd.DataFrame,
                     metrics: pd.DataFrame | None = None) -> pd.DataFrame:
    """Skor tablosuna metrik tablosundan ek sütunları (VaR/CVaR/reel/dönemsel
    getiri/AUM/yaş) ekler — report.generate ile aynı merge. `metrics` None ise
    skor tablosu olduğu gibi döner."""
    if scored is None or scored.empty:
        return pd.DataFrame()
    df = scored.copy()
    if metrics is None or metrics.empty:
        return df
    extra = [c for c in _ENRICH_COLS if c in metrics.columns and c not in df.columns]
    if extra:
        df = df.merge(metrics[["Fon Kodu"] + extra], on="Fon Kodu", how="left")
    return df


def enriched_frame(fund_type: str = "YAT") -> pd.DataFrame:
    """Karar bayrakları + metrik zenginleştirmesi uygulanmış tam çerçeve
    (sayfaların ortak girdisi)."""
    scored = load_scored(fund_type)
    if scored is None or scored.empty:
        return pd.DataFrame()
    enriched = metrics_enriched(scored, load_metrics(fund_type))
    return allocation.add_decision_flags(enriched)


@st.cache_data(show_spinner=False)
def _price_pivot(path_str: str, mtime: float) -> pd.DataFrame:
    return charts.price_pivot(pd.read_parquet(path_str))


def price_pivot(fund_type: str = "YAT") -> pd.DataFrame | None:
    """Önbellekli Tarih×Fon fiyat pivotu (sayfalar ~700k satırı yeniden
    pivotlamasın). Yeni `tefas run` sonrası mtime değişince tazelenir."""
    p = config.paths_for(fund_type).combined_parquet
    if not p.exists():
        return None
    return _price_pivot(str(p), _mtime(p))


@st.cache_data(show_spinner=False)
def _monthly(path_str: str, mtime: float) -> pd.DataFrame:
    return charts.prep_monthly_returns(charts.price_pivot(pd.read_parquet(path_str)))


def monthly_returns(fund_type: str = "YAT") -> pd.DataFrame | None:
    """Önbellekli tüm-evren aylık getiri tablosu (ısı takvimlerinde evren
    medyan satırı için tekrar tekrar hesaplanmasın)."""
    p = config.paths_for(fund_type).combined_parquet
    if not p.exists():
        return None
    return _monthly(str(p), _mtime(p))


def prepare_decision_frame(scored: pd.DataFrame) -> pd.DataFrame:
    """Dashboard/PDF ortak karar bayraklarini skor tablosuna ekler."""
    if scored is None or scored.empty:
        return pd.DataFrame()
    return allocation.add_decision_flags(scored)


def recommendation_universe(scored: pd.DataFrame) -> pd.DataFrame:
    """Ana oneri evreni; veri yetersiz fixture'larda kontrollu geri duer."""
    df = prepare_decision_frame(scored)
    if df.empty:
        return df
    main = df[df["Oneri_Uygun"]].copy() if "Oneri_Uygun" in df.columns else df.copy()
    if not main.empty:
        return main
    elig = df[df["Uygun"].fillna(False)].copy() if "Uygun" in df.columns else df.copy()
    return elig if not elig.empty else df


def model_portfolio(scored: pd.DataFrame) -> list[dict]:
    """Dashboard model portfoyu: rapordaki allocation kurallariyla ayni."""
    universe = recommendation_universe(scored)
    if universe.empty:
        return []
    model = allocation.build_portfolio(universe)
    if not model:
        model = allocation.build_portfolio(universe, exclude_young=False)
    return model


def sidebar_fund_type() -> str:
    """Ortak kenar cubuu: fon tipi secimi (sayfalar arasi tutarli)."""
    return st.sidebar.selectbox(
        "Fon tipi", list(FUND_TYPES), format_func=lambda k: f"{FUND_TYPES[k]} ({k})",
        key="fund_type")


def no_data_warning(fund_type: str) -> None:
    st.warning(f"`Output/` altinda {FUND_TYPES[fund_type]} verisi yok. "
               "nce terminalde `tefas run` calitirin.")


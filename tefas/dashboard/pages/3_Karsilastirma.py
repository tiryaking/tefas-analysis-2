"""Karşılaştırma: serbest seçilen 2–8 fonu yan yana kıyaslar.

PDF karşılaştırma modu comparison_config.txt + yeniden koşu gerektirir; burada
tek multiselect ile anında. Verdict, radar, en-iyi-hücre vurgulu metrik matrisi,
büyüme/drawdown/dönemsel/aylık-ısı ve korelasyon — hepsi comparison.py +
figures.py paylaşılan mantığından (PDF ile aynı 'en iyi' kararları).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import streamlit as st

from tefas import charts, comparison, portfolio as pf, themes
from tefas.dashboard import data, figures, ui

st.set_page_config(page_title="Karşılaştırma", page_icon=":scales:", layout="wide")
ft = data.sidebar_fund_type()
st.title("Fon Karşılaştırma")

scored = data.enriched_frame(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty or combined is None:
    data.no_data_warning(ft)
    st.stop()

default = data.model_portfolio(scored)
default_codes = [str(p["Fon Kodu"]) for p in default][:4] if default else \
    scored.nlargest(3, "Overall_Score")["Fon Kodu"].astype(str).tolist()
codes = ui.fund_multiselect(scored, key="cmp_codes", default=default_codes)

if len(codes) < 2:
    st.info("Karşılaştırmak için en az 2 fon seçin.")
    st.stop()

met = scored[scored["Fon Kodu"].astype(str).isin(codes)].reset_index(drop=True)

# ── Verdict + radar ───────────────────────────────────────────────────────────
c1, c2 = st.columns([1, 1])
with c1:
    st.subheader("Öne çıkanlar")
    verdict = pd.DataFrame(comparison.verdict_rows(met), columns=["Ölçüt", "Kazanan"])
    st.dataframe(verdict, width="stretch", hide_index=True)
with c2:
    st.plotly_chart(figures.fig_radar(met), width="stretch")

# ── Karşılaştırma matrisi (en-iyi hücre vurgulu) ──────────────────────────────
st.subheader("Karşılaştırma Tablosu")
table, best_map = comparison.comparison_matrix(met)


def _highlight(_df):
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    for ri, ci in best_map.items():
        if ci is not None:
            styles.iloc[ri, ci] = "background-color: #e3f4ec; font-weight: 600"
    return styles


st.dataframe(table.style.apply(_highlight, axis=None), width="stretch")
ui.download_df(table.reset_index(names="Metrik"), f"karsilastirma_{ft.lower()}.csv", key="dl_cmp")

# ── Büyüme + dönemsel ─────────────────────────────────────────────────────────
pivot = data.price_pivot(ft)
cmap = figures.color_map(codes)
g1, g2 = st.columns(2)
with g1:
    norm = charts.prep_growth(pivot, codes) if pivot is not None else None
    st.plotly_chart(figures.fig_growth(norm, cmap=cmap,
                                       benchmark=themes.theme_median_growth(combined),
                                       title="Kümülatif Büyüme (ortak dönem)"), width="stretch")
with g2:
    st.plotly_chart(figures.fig_period_bars(met), width="stretch")

# ── Drawdown + korelasyon ─────────────────────────────────────────────────────
d1, d2 = st.columns(2)
with d1:
    if pivot is not None:
        st.plotly_chart(figures.fig_drawdown_lines(pivot, codes, cmap=cmap), width="stretch")
with d2:
    rets = pf.returns_matrix(combined, codes)
    if rets.shape[1] >= 2:
        st.plotly_chart(figures.fig_corr_heatmap(rets.corr()), width="stretch")

# ── Aylık ısı takvimi ──────────────────────────────────────────────────────────
if pivot is not None:
    monthly = charts.prep_monthly_returns(pivot)
    st.plotly_chart(figures.fig_monthly_heatmap(monthly, codes, median_label="Grup medyanı"),
                    width="stretch")

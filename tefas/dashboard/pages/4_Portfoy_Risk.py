"""Portföy & Risk: model portföy, profil bazlı öneriler, kovaryans riski,
yeni fırsatlar ve canlı what-if laboratuvarı.

Kişisel portföy YOK — bunlar modelin ürettiği örnek/aday portföydür (istek #2).
Tüm mantık allocation.py + portfolio.py'den; sayfa ince kalır.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from tefas import allocation, charts, portfolio as pf
from tefas.dashboard import data, figures, ui

st.set_page_config(page_title="Portföy & Risk", page_icon=":bank:", layout="wide")
ft = data.sidebar_fund_type()
st.title("Portföy & Risk")
st.caption("Modelin ürettiği örnek portföy ve risk analizi — kişisel portföy değildir, "
           "yatırım tavsiyesi değildir.")

scored = data.load_scored(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

decision = data.enriched_frame(ft)
universe = data.recommendation_universe(scored)
model = data.model_portfolio(scored)

tab_model, tab_profiles, tab_risk, tab_ops, tab_whatif = st.tabs(
    ["Model Portföy", "Profil Önerileri", "Risk", "Yeni Fırsatlar", "What-if Lab"])

# ── Model Portföy ─────────────────────────────────────────────────────────────
with tab_model:
    if not model:
        st.info("Model portföy kurulamadı (yeterli uygun fon yok).")
    else:
        port = pd.DataFrame(model)
        exp_ret, vol_lo, vol_hi = allocation.portfolio_expected(model)
        c1, c2 = st.columns([1.3, 1])
        with c1:
            show = [c for c in ["Fon Kodu", "Fon Adi", "Profil", "Tema", "Agirlik",
                                "Yillik_Getiri", "Yillik_Volatilite", "Karar_Bayraklari"]
                    if c in port.columns]
            st.dataframe(port[show], width="stretch", hide_index=True,
                         column_config={"Agirlik": st.column_config.NumberColumn("Ağırlık %", format="%.1f")})
            ui.download_df(port[show], f"model_portfoy_{ft.lower()}.csv", key="dl_model")
        with c2:
            st.plotly_chart(px.pie(port, names="Fon Kodu", values="Agirlik", hole=0.45)
                            .update_layout(height=340, margin=dict(t=10, b=10)), width="stretch")
        st.metric("Beklenen yıllık getiri (ağırlıklı)", f"%{exp_ret:.1f}")

# ── Profil Önerileri ─────────────────────────────────────────────────────────
with tab_profiles:
    st.caption("Her risk profili için profil skoruna göre ilk 6 uygun fon.")
    for score_key, label, _, _ in allocation.PROFILE_PLAN:
        ranked = allocation.profile_ranked(decision, score_key)
        col = f"{score_key}_Score"
        if ranked.empty or col not in ranked.columns:
            continue
        st.subheader(label)
        cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", col, "Yillik_Getiri",
                            "Yillik_Volatilite", "Sharpe_Orani", "Max_Drawdown"]
                if c in ranked.columns]
        st.dataframe(ranked.head(6)[cols], width="stretch", hide_index=True,
                     column_config={col: st.column_config.ProgressColumn(
                         "Profil skoru", min_value=0, max_value=100, format="%.1f")})

# ── Risk ──────────────────────────────────────────────────────────────────────
with tab_risk:
    if combined is None or not model:
        st.info("Risk analizi için combined parquet ve model portföy gerekli.")
    else:
        risk = pf.portfolio_risk(combined, model)
        if risk is None:
            st.info("Kovaryans hesaplanamadı; ortak fiyat geçmişi yetersiz.")
        else:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Portföy vol", f"%{risk['portfolio_vol']:.1f}")
            r2.metric("Ağırlıklı vol", f"%{risk['weighted_avg_vol']:.1f}")
            r3.metric("Çeşitlendirme kazancı", f"%{risk['diversification_gain']:.1f}")
            r4.metric("Ort. korelasyon", f"{risk['avg_correlation']:.2f}")
            st.plotly_chart(figures.fig_weight_vs_risk(risk), width="stretch")

            codes = [p["Fon Kodu"] for p in model]
            dd = pf.portfolio_drawdown(combined, model)
            if dd is not None:
                st.plotly_chart(figures.fig_underwater(*dd), width="stretch")
            rets = pf.returns_matrix(combined, codes)
            if rets.shape[1] >= 2:
                st.plotly_chart(figures.fig_corr_heatmap(rets.corr()), width="stretch")

        # Tail-risk tablosu (ilk 12 aday)
        st.subheader("Tail-Risk (kuyruk riski)")
        tr_cols = [c for c in ["Fon Kodu", "Yillik_Getiri", "Yillik_Volatilite",
                               "VaR_95", "VaR_99", "CVaR_95", "En_Kotu_Gun", "Max_Drawdown"]
                   if c in universe.columns]
        tail = universe.nlargest(12, "Overall_Score")[tr_cols] if "Overall_Score" in universe.columns \
            else universe[tr_cols].head(12)
        st.dataframe(tail, width="stretch", hide_index=True)
        ui.download_df(tail, f"tail_risk_{ft.lower()}.csv", key="dl_tail")

# ── Yeni Fırsatlar ─────────────────────────────────────────────────────────────
with tab_ops:
    st.caption("Verideki ilk fiyat gününe göre 2–6 ay önce kurulmuş genç fonlar; "
               "Fırsat Skoru yalnızca bu kohort içindeki yüzdelik sıralardan hesaplanır.")
    newops = allocation.new_opportunities(decision, combined) if combined is not None \
        else pd.DataFrame()
    if newops.empty:
        st.info("Bu dönemde kohorta giren yeni fon yok.")
    else:
        no_cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Yas_Ay", "Firsat_Skoru",
                               "Getiri_1A", "Getiri_3A", "Yillik_Volatilite", "Max_Drawdown",
                               "Fon_Toplam_Deger_Milyon_TL"] if c in newops.columns]
        st.dataframe(newops.head(10)[no_cols], width="stretch", hide_index=True)
        ui.download_df(newops[no_cols], f"yeni_firsatlar_{ft.lower()}.csv", key="dl_ops")
        top_codes = newops.head(5)["Fon Kodu"].astype(str).tolist()
        pivot = data.price_pivot(ft)
        if pivot is not None:
            st.plotly_chart(figures.fig_growth(
                charts.prep_growth(pivot, top_codes),
                title="Yeni Fırsat Fonları — Kümülatif Büyüme"), width="stretch")

# ── What-if Lab ────────────────────────────────────────────────────────────────
with tab_whatif:
    st.caption("Model kurallarını canlı değiştir — `tefas.model.json` diske DOKUNULMAZ, "
               "yalnızca bellekte yeniden hesaplanır.")
    w1, w2, w3 = st.columns(3)
    theme_cap = w1.slider("Tema tavanı", 1, 3, 1, help="Bir temadan en çok kaç fon")
    fill = w2.toggle("Dar evren doldurma", value=True)
    exclude_young = w3.toggle("Genç fonları hariç tut", value=True)
    wf_model = allocation.build_portfolio(universe if not universe.empty else decision,
                                          theme_cap=theme_cap, fill=fill,
                                          exclude_young=exclude_young)
    if not wf_model:
        st.info("Bu ayarlarla portföy kurulamadı.")
    else:
        wf = pd.DataFrame(wf_model)
        base_codes = {p["Fon Kodu"] for p in model}
        wf_codes = {p["Fon Kodu"] for p in wf_model}
        c1, c2, c3 = st.columns(3)
        c1.metric("Fon sayısı", len(wf_model))
        c2.metric("Tema sayısı", wf["Tema"].nunique())
        c3.metric("Varsayılandan farklı", len(wf_codes ^ base_codes))
        show = [c for c in ["Fon Kodu", "Fon Adi", "Profil", "Tema", "Agirlik"] if c in wf.columns]
        st.dataframe(wf[show], width="stretch", hide_index=True)
        if combined is not None:
            wf_risk = pf.portfolio_risk(combined, wf_model)
            if wf_risk is not None:
                st.metric("What-if portföy volatilitesi", f"%{wf_risk['portfolio_vol']:.1f}")

"""Karar Merkezi: öneri, validasyon ve risk merkezi."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas import portfolio as pf
from tefas.dashboard import data

st.set_page_config(page_title="Karar Merkezi", page_icon="OK", layout="wide")
ft = data.sidebar_fund_type()
st.title("Karar Merkezi")

scored = data.load_scored(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

combined = data.load_combined(ft)
decision = data.prepare_decision_frame(scored)
universe = data.recommendation_universe(scored)
model = data.model_portfolio(scored)
validation_summary = data.load_validation(ft)

tab_port, tab_validation, tab_risk = st.tabs([
    "Portföy Önerisi", "Model Doğrulama", "Risk Merkezi"
])

with tab_port:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Analiz edilen fon", f"{len(decision):,}")
    c2.metric("Ana öneri evreni", f"{len(universe):,}")
    c3.metric("İzleme listesi", f"{int(decision.get('Izleme_Listesi_Adayi', pd.Series(dtype=bool)).sum()):,}")
    c4.metric("rf altı", f"{int((~decision.get('Rf_Ustu', pd.Series(True, index=decision.index)).fillna(False).astype(bool)).sum()):,}")

    cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                        "Yillik_Volatilite", "Max_Drawdown", "Karar_Bayraklari"]
            if c in universe.columns]
    st.dataframe(universe.nlargest(min(12, len(universe)), "Overall_Score")[cols],
                 use_container_width=True, hide_index=True,
                 column_config={"Overall_Score": st.column_config.ProgressColumn(
                     "Skor", min_value=0, max_value=100, format="%.1f")})

    if model:
        port = pd.DataFrame(model)
        show = [c for c in ["Fon Kodu", "Fon Adi", "Profil", "Tema", "Agirlik",
                            "Yillik_Getiri", "Yillik_Volatilite", "Karar_Bayraklari"]
                if c in port.columns]
        st.subheader("Model portföy")
        st.dataframe(port[show], use_container_width=True, hide_index=True,
                     column_config={
                         "Agirlik": st.column_config.NumberColumn("Ağırlık %", format="%.1f"),
                         "Yillik_Getiri": st.column_config.NumberColumn("Yıl. Getiri %", format="%.1f"),
                         "Yillik_Volatilite": st.column_config.NumberColumn("Volatilite %", format="%.1f"),
                     })
    else:
        st.info("Model portföy kurulamadı; uygun evren boş veya skor kolonları eksik.")

with tab_validation:
    if validation_summary.available:
        v = validation_summary.table.copy()
        st.dataframe(v, use_container_width=True, hide_index=True,
                     column_config={
                         "Portfoy_Ort": st.column_config.NumberColumn("Portföy Ort. %", format="%.2f"),
                         "Evren_Ort": st.column_config.NumberColumn("Evren Ort. %", format="%.2f"),
                         "Ort_Fark": st.column_config.NumberColumn("Ort. Fark %", format="%.2f"),
                         "Medyan_Fark": st.column_config.NumberColumn("Medyan Fark %", format="%.2f"),
                         "Isabet_Orani": st.column_config.NumberColumn("Hit-rate", format="%.2f"),
                     })
        fig = go.Figure()
        fig.add_bar(x=v["Ufuk_Ay"].astype(str), y=v["Ort_Fark"], marker_color="#1f5fb0")
        fig.update_layout(height=360, title="Ortalama ileri dönem farkı",
                          xaxis_title="Ufuk (ay)", yaxis_title="Portföy - Evren (%)",
                          margin=dict(t=48, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning(validation_summary.message)

with tab_risk:
    flags = [("Kısa geçmiş", "Kisa_Gecmis"), ("Düşük AUM", "Dusuk_AUM"),
             ("Yüksek drawdown", "Yuksek_Drawdown"),
             ("Düşük oynaklık ama rf altı", "Dusuk_Vol_Rf_Alti")]
    rows = [{"Bayrak": label, "Fon Sayısı": int(decision[col].fillna(False).astype(bool).sum())}
            for label, col in flags if col in decision.columns]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if combined is None or not model:
        st.info("Risk katkısı için combined parquet ve model portföy gerekli.")
    else:
        risk = pf.portfolio_risk(combined, model)
        if risk is None:
            st.info("Kovaryans hesaplanamadı; ortak fiyat geçmişi yetersiz.")
        else:
            rc = risk.get("risk_contributions") or {}
            wt = risk.get("weights") or {}
            codes = list(rc)
            fig = go.Figure()
            fig.add_bar(name="Ağırlık", x=codes, y=[wt.get(c, 0) * 100 for c in codes],
                        marker_color="#1f5fb0")
            fig.add_bar(name="Risk katkısı", x=codes, y=[rc.get(c, 0) * 100 for c in codes],
                        marker_color="#c0622d")
            fig.update_layout(barmode="group", height=420,
                              title=f"Portföy vol %{risk['portfolio_vol']:.1f} | Ort. korelasyon {risk['avg_correlation']:.2f}",
                              yaxis_title="%", margin=dict(t=48, b=20))
            st.plotly_chart(fig, use_container_width=True)

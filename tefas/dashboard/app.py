"""TEFAS Dashboard: interactive decision and analysis cockpit."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tefas import model_config, portfolio as pf
from tefas.dashboard import data

st.set_page_config(page_title="TEFAS Analiz Merkezi", page_icon=":bar_chart:", layout="wide")


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def _fmt_pct(x: float | int | None, dec: int = 1) -> str:
    return "-" if pd.isna(x) else f"%{float(x):.{dec}f}"


def _safe_top(df: pd.DataFrame, col: str, n: int = 10, ascending: bool = False) -> pd.DataFrame:
    if df.empty or col not in df.columns:
        return df.iloc[0:0].copy()
    work = df.copy()
    work[col] = pd.to_numeric(work[col], errors="coerce")
    return work.sort_values(col, ascending=ascending).head(n)


def _theme_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Tema" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    for col in ["Overall_Score", "Yillik_Getiri", "Yillik_Volatilite", "Max_Drawdown",
                "Sharpe_Orani", "Fon_Toplam_Deger_Milyon_TL"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return (work.groupby("Tema", dropna=False)
            .agg(Fon_Sayisi=("Fon Kodu", "count"),
                 Ort_Skor=("Overall_Score", "mean"),
                 Ort_Getiri=("Yillik_Getiri", "mean"),
                 Ort_Vol=("Yillik_Volatilite", "mean"),
                 Medyan_DD=("Max_Drawdown", "median"),
                 Ort_Sharpe=("Sharpe_Orani", "mean"),
                 Toplam_AUM=("Fon_Toplam_Deger_Milyon_TL", "sum"))
            .round(2).reset_index().sort_values("Ort_Skor", ascending=False))


def _flag_count(df: pd.DataFrame, col: str) -> int:
    return int(df[col].fillna(False).astype(bool).sum()) if col in df.columns else 0


ft = data.sidebar_fund_type()
st.title("TEFAS Analiz Merkezi")
st.caption("Mevcut Output parquet/CSV ciktilarindan okur; harici veri cekmez ve yatirim tavsiyesi deildir.")

scored = data.load_scored(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

combined = data.load_combined(ft)
decision = data.prepare_decision_frame(scored)
universe = data.recommendation_universe(scored)
model = data.model_portfolio(scored)
validation_summary = data.load_validation(ft)
model_cfg = model_config.current()

for col in ["Overall_Score", "Yillik_Getiri", "Yillik_Volatilite", "Sharpe_Orani",
            "Sortino_Orani", "Max_Drawdown", "Reel_Getiri_1Y", "Fon_Toplam_Deger_Milyon_TL"]:
    if col in decision.columns:
        decision[col] = pd.to_numeric(decision[col], errors="coerce")
    if col in universe.columns:
        universe[col] = pd.to_numeric(universe[col], errors="coerce")

as_of = pd.to_datetime(combined["Tarih"]).max().date() if combined is not None and not combined.empty else "-"
rf_under = int((~decision.get("Rf_Ustu", pd.Series(True, index=decision.index)).fillna(False).astype(bool)).sum())

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Fon", f"{len(decision):,}")
k2.metric("Ana oneri evreni", f"{len(universe):,}")
k3.metric("Model", model_cfg.version)
k4.metric("Veri sonu", str(as_of))
k5.metric("rf alti", f"{rf_under:,}")
k6.metric("Izleme", f"{_flag_count(decision, 'Izleme_Listesi_Adayi'):,}")

tab_decision, tab_screener, tab_model, tab_themes, tab_validation, tab_risk = st.tabs([
    "Karar zeti", "Fon Tarama", "Model Portfoy", "Tema Analizi", "Model Dorulama", "Risk Merkezi"
])

with tab_decision:
    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("En guclu ana oneri adaylari")
        cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                            "Yillik_Volatilite", "Sharpe_Orani", "Max_Drawdown",
                            "Reel_Getiri_1Y", "Karar_Bayraklari"] if c in universe.columns]
        st.dataframe(_safe_top(universe, "Overall_Score", 15)[cols],
                     width="stretch", hide_index=True,
                     column_config={
                         "Overall_Score": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100, format="%.1f"),
                         "Yillik_Getiri": st.column_config.NumberColumn("Yil. Getiri %", format="%.1f"),
                         "Yillik_Volatilite": st.column_config.NumberColumn("Volatilite %", format="%.1f"),
                         "Max_Drawdown": st.column_config.NumberColumn("Max DD %", format="%.1f"),
                     })
    with right:
        st.subheader("Uyari bayraklari")
        flags = pd.DataFrame([
            {"Bayrak": "Kisa gecmi", "Fon Sayisi": _flag_count(decision, "Kisa_Gecmis")},
            {"Bayrak": "Duuk AUM", "Fon Sayisi": _flag_count(decision, "Dusuk_AUM")},
            {"Bayrak": "Yuksek drawdown", "Fon Sayisi": _flag_count(decision, "Yuksek_Drawdown")},
            {"Bayrak": "Duuk oynaklik ama rf alti", "Fon Sayisi": _flag_count(decision, "Dusuk_Vol_Rf_Alti")},
            {"Bayrak": "Reel negatif", "Fon Sayisi": int((_num(decision, "Reel_Getiri_1Y") <= 0).sum())},
        ])
        fig = px.bar(flags, x="Fon Sayisi", y="Bayrak", orientation="h", text="Fon Sayisi",
                     color="Bayrak", color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(height=360, showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, width="stretch")

    watch = decision[decision.get("Izleme_Listesi_Adayi", False).fillna(False)] \
        if "Izleme_Listesi_Adayi" in decision.columns else pd.DataFrame()
    if not watch.empty:
        st.subheader("Izleme listesi adaylari")
        wcols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                             "Veri_Noktasi_Sayisi", "Karar_Bayraklari"] if c in watch.columns]
        st.dataframe(_safe_top(watch, "Overall_Score", 12)[wcols], width="stretch", hide_index=True)

with tab_screener:
    st.subheader("Etkileimli fon tarama")
    f1, f2, f3, f4, f5 = st.columns([2, 1, 1, 1, 1])
    q = f1.text_input("Kod/ad ara", "")
    themes = sorted(decision["Tema"].dropna().unique()) if "Tema" in decision.columns else []
    selected_themes = f2.multiselect("Tema", themes)
    min_score = f3.slider("Min skor", 0, 100, 50, 5)
    max_dd = f4.slider("Maks drawdown", 0, 80, 80, 5)
    main_only = f5.toggle("Ana evren", value=True)

    mask = pd.Series(True, index=decision.index)
    if q.strip():
        s = q.strip().upper()
        mask &= (decision["Fon Kodu"].astype(str).str.upper().str.contains(s, regex=False)
                 | decision["Fon Adi"].astype(str).str.upper().str.contains(s, regex=False))
    if selected_themes:
        mask &= decision["Tema"].isin(selected_themes)
    mask &= _num(decision, "Overall_Score").fillna(0) >= min_score
    mask &= _num(decision, "Max_Drawdown").fillna(999) <= max_dd
    if main_only and "Oneri_Uygun" in decision.columns:
        mask &= decision["Oneri_Uygun"].fillna(False)
    filtered = decision[mask].sort_values("Overall_Score", ascending=False)

    scatter_df = filtered.dropna(subset=["Yillik_Volatilite", "Yillik_Getiri"])
    if len(scatter_df) >= 2:
        fig = px.scatter(scatter_df, x="Yillik_Volatilite", y="Yillik_Getiri",
                         color="Tema" if "Tema" in scatter_df.columns else None,
                         size="Fon_Toplam_Deger_Milyon_TL" if "Fon_Toplam_Deger_Milyon_TL" in scatter_df.columns else None,
                         hover_name="Fon Kodu", hover_data=["Fon Adi", "Overall_Score", "Karar_Bayraklari"],
                         labels={"Yillik_Volatilite": "Volatilite %", "Yillik_Getiri": "Yillik getiri %"})
        fig.update_layout(height=520, margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")
    display_cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                                "Yillik_Volatilite", "Sharpe_Orani", "Sortino_Orani",
                                "Max_Drawdown", "Fon_Toplam_Deger_Milyon_TL", "Karar_Bayraklari"]
                    if c in filtered.columns]
    st.dataframe(filtered[display_cols], width="stretch", hide_index=True, height=420)

with tab_model:
    st.subheader("Model portfoy")
    if not model:
        st.info("Model portfoy kurulamadi.")
    else:
        port = pd.DataFrame(model)
        c1, c2 = st.columns([1.2, 1])
        with c1:
            show = [c for c in ["Fon Kodu", "Fon Adi", "Profil", "Tema", "Agirlik",
                                "Yillik_Getiri", "Yillik_Volatilite", "Karar_Bayraklari"] if c in port.columns]
            st.dataframe(port[show], width="stretch", hide_index=True,
                         column_config={"Agirlik": st.column_config.NumberColumn("Airlik %", format="%.1f")})
        with c2:
            fig = px.pie(port, names="Fon Kodu", values="Agirlik", hole=0.45)
            fig.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

with tab_themes:
    st.subheader("Tema analizi")
    themes_df = _theme_summary(universe)
    if themes_df.empty:
        st.info("Tema ozeti uretilemedi.")
    else:
        fig = px.scatter(themes_df, x="Ort_Vol", y="Ort_Getiri", size="Fon_Sayisi",
                         color="Tema", hover_data=["Ort_Skor", "Medyan_DD", "Toplam_AUM"],
                         labels={"Ort_Vol": "Ort. volatilite %", "Ort_Getiri": "Ort. getiri %"})
        fig.update_layout(height=500, legend_title_text="Tema", margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(themes_df, width="stretch", hide_index=True)

with tab_validation:
    st.subheader("Walk-forward model dorulama")
    if validation_summary.available:
        v = validation_summary.table.copy()
        st.dataframe(v, width="stretch", hide_index=True)
        fig = go.Figure()
        fig.add_bar(name="Ort. fark", x=v["Ufuk_Ay"].astype(str), y=v["Ort_Fark"],
                    marker_color="#1f5fb0")
        fig.add_scatter(name="Hit-rate", x=v["Ufuk_Ay"].astype(str), y=v["Isabet_Orani"] * 100,
                        yaxis="y2", mode="lines+markers", marker_color="#0f8a6a")
        fig.update_layout(height=420, xaxis_title="Ufuk (ay)", yaxis_title="Fark (%)",
                          yaxis2=dict(title="Hit-rate %", overlaying="y", side="right", range=[0, 100]),
                          margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning(validation_summary.message)

with tab_risk:
    st.subheader("Risk merkezi")
    if combined is None or not model:
        st.info("Risk merkezi icin combined parquet ve model portfoy gerekli.")
    else:
        risk = pf.portfolio_risk(combined, model)
        if risk is None:
            st.info("Kovaryans hesaplanamadi; ortak fiyat gecmii yetersiz.")
        else:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Portfoy vol", _fmt_pct(risk["portfolio_vol"]))
            r2.metric("Airlikli vol", _fmt_pct(risk["weighted_avg_vol"]))
            r3.metric("eitlendirme kazanci", _fmt_pct(risk["diversification_gain"]))
            r4.metric("Ort. korelasyon", f"{risk['avg_correlation']:.2f}")
            rc = risk.get("risk_contributions") or {}
            wt = risk.get("weights") or {}
            codes = list(rc)
            fig = go.Figure()
            fig.add_bar(name="Airlik", y=codes, x=[wt.get(c, 0) * 100 for c in codes],
                        orientation="h", marker_color="#1f5fb0")
            fig.add_bar(name="Risk katkisi", y=codes, x=[rc.get(c, 0) * 100 for c in codes],
                        orientation="h", marker_color="#c0622d")
            fig.update_layout(barmode="group", height=max(420, 58 * len(codes)),
                              xaxis_title="%", margin=dict(t=20, b=20))
            st.plotly_chart(fig, width="stretch")


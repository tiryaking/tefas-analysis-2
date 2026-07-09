"""TEFAS Analiz Merkezi — Özet (yönetici katmanı).

Salt-okuma BI paneli giriş sayfası: KPI'lar, en güçlü öneri adayları, uyarı
bayrakları ve evren sağlığı grafikleri (getiri/Sharpe dağılımı, benchmark geçme
oranları, tema dağılımı). Derinlemesine analiz soldaki sayfalarda:
Fon Keşif · Fon Detay · Karşılaştırma · Portföy & Risk · Model & Metodoloji.
Kişisel portföy özelliği BİLEREK yoktur (yalnızca `tefas holdings` CLI'sinde).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from tefas import config, model_config
from tefas.dashboard import data, ui



def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


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
    for col in ["Overall_Score", "Yillik_Getiri", "Fon_Toplam_Deger_Milyon_TL"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    return (work.groupby("Tema", dropna=False)
            .agg(Fon_Sayisi=("Fon Kodu", "count"),
                 Ort_Skor=("Overall_Score", "mean"),
                 Ort_Getiri=("Yillik_Getiri", "mean"))
            .round(1).reset_index().sort_values("Fon_Sayisi", ascending=True))


def _flag_count(df: pd.DataFrame, col: str) -> int:
    return int(df[col].fillna(False).astype(bool).sum()) if col in df.columns else 0


ft = data.sidebar_fund_type()
st.title("TEFAS Analiz Merkezi")
st.caption("Mevcut Output parquet/CSV çıktılarından okur; harici veri çekmez ve "
           "yatırım tavsiyesi değildir. Detaylı analiz için soldaki sayfaları kullanın.")

scored = data.load_scored(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

combined = data.load_combined(ft)
decision = data.enriched_frame(ft)
universe = data.recommendation_universe(scored)
mac = config.macro()
model_cfg = model_config.current()

for col in ["Overall_Score", "Yillik_Getiri", "Yillik_Volatilite", "Sharpe_Orani",
            "Reel_Getiri_1Y", "Max_Drawdown"]:
    if col in universe.columns:
        universe[col] = pd.to_numeric(universe[col], errors="coerce")

as_of = pd.to_datetime(combined["Tarih"]).max().date() if combined is not None and not combined.empty else "-"
rf_under = int((~decision.get("Rf_Ustu", pd.Series(True, index=decision.index)).fillna(False).astype(bool)).sum())

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Fon", f"{len(decision):,}")
k2.metric("Ana öneri evreni", f"{len(universe):,}")
k3.metric("Model", model_cfg.version)
k4.metric("Veri sonu", str(as_of))
k5.metric("rf altı", f"{rf_under:,}")
k6.metric("İzleme", f"{_flag_count(decision, 'Izleme_Listesi_Adayi'):,}")

st.divider()

# ── En güçlü öneri adayları (tam genişlik, formatlı — yatay scroll yok) ────────
st.subheader("En güçlü ana öneri adayları")
cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                    "Yillik_Volatilite", "Sharpe_Orani", "Max_Drawdown",
                    "Reel_Getiri_1Y", "Karar_Bayraklari"] if c in universe.columns]
top = _safe_top(universe, "Overall_Score", 15)[cols]
st.dataframe(top, width="stretch", hide_index=True, column_config=ui.metric_column_config())
ui.download_df(top, f"oneri_adaylari_{ft.lower()}.csv", key="dl_top")

# ── Uyarı bayrakları ──────────────────────────────────────────────────────────
st.subheader("Uyarı bayrakları")
flags = pd.DataFrame([
    {"Bayrak": "Kısa geçmiş", "Fon Sayısı": _flag_count(decision, "Kisa_Gecmis")},
    {"Bayrak": "Düşük AUM", "Fon Sayısı": _flag_count(decision, "Dusuk_AUM")},
    {"Bayrak": "Yüksek drawdown", "Fon Sayısı": _flag_count(decision, "Yuksek_Drawdown")},
    {"Bayrak": "Düşük oynaklık ama rf altı", "Fon Sayısı": _flag_count(decision, "Dusuk_Vol_Rf_Alti")},
    {"Bayrak": "Reel negatif", "Fon Sayısı": int((_num(decision, "Reel_Getiri_1Y") <= 0).sum())},
])
fig = px.bar(flags, x="Fon Sayısı", y="Bayrak", orientation="h", text="Fon Sayısı",
             color="Bayrak", color_discrete_sequence=px.colors.qualitative.Set2)
fig.update_layout(height=300, showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
st.plotly_chart(fig, width="stretch")

# ── Evren sağlığı: dağılım + benchmark geçme + tema (PDF'ten portlanan) ────────
st.divider()
st.subheader("Evren Sağlığı")
d1, d2 = st.columns(2)
ret = _num(decision, "Yillik_Getiri").dropna()
shp = _num(decision, "Sharpe_Orani").dropna()
with d1:
    if len(ret) >= 5:
        rlo, rhi = np.percentile(ret, 1), np.percentile(ret, 99)
        fig = px.histogram(ret.clip(rlo, rhi), nbins=40, title="Yıllık Getiri Dağılımı (%)")
        for val, lbl, col in [(mac.risk_free_rate, "rf", "#6b7785"),
                              (mac.inflation_rate, "TÜFE", "#c0392b"),
                              (mac.policy_rate, "Politika", "#e0a526")]:
            if rlo <= val <= rhi:
                fig.add_vline(x=val, line_dash="dash", line_color=col,
                              annotation_text=f"{lbl} %{val:.0f}")
        fig.update_layout(height=340, showlegend=False, margin=dict(t=40, b=10))
        st.plotly_chart(fig, width="stretch")
with d2:
    if len(shp) >= 5:
        slo, shi = np.percentile(shp, 1), np.percentile(shp, 99)
        fig = px.histogram(shp.clip(slo, shi), nbins=40, title="Sharpe Oranı Dağılımı",
                           color_discrete_sequence=["#0f8a6a"])
        fig.add_vline(x=float(shp.median()), line_dash="dash", line_color="#6b7785",
                      annotation_text=f"medyan {shp.median():.2f}")
        fig.update_layout(height=340, showlegend=False, margin=dict(t=40, b=10))
        st.plotly_chart(fig, width="stretch")

b1, b2 = st.columns(2)
with b1:
    ret_all = _num(decision, "Yillik_Getiri")
    real_all = _num(decision, "Reel_Getiri_1Y")
    n = len(decision)
    beats = pd.DataFrame([
        {"Ölçüt": f"Mevduat/rf (%{mac.risk_free_rate:.0f})", "Oran": float((ret_all > mac.risk_free_rate).mean() * 100)},
        {"Ölçüt": f"Politika (%{mac.policy_rate:.0f})", "Oran": float((ret_all > mac.policy_rate).mean() * 100)},
        {"Ölçüt": f"Enflasyon (%{mac.inflation_rate:.0f})", "Oran": float((ret_all > mac.inflation_rate).mean() * 100)},
        {"Ölçüt": "Pozitif reel", "Oran": float((real_all > 0).mean() * 100)},
    ])
    fig = px.bar(beats, x="Oran", y="Ölçüt", orientation="h", text="Oran",
                 title="Evren Benchmark'ları Ne Kadar Geçiyor? (%)",
                 range_x=[0, 100])
    fig.update_traces(texttemplate="%{text:.0f}%")
    fig.update_layout(height=300, showlegend=False, margin=dict(t=40, b=10))
    st.plotly_chart(fig, width="stretch")
with b2:
    theme_mix = _theme_summary(universe)
    if not theme_mix.empty:
        fig = px.bar(theme_mix.tail(12), x="Fon_Sayisi", y="Tema", orientation="h",
                     text="Fon_Sayisi", title="Tema Dağılımı (öneri evreni)",
                     hover_data=["Ort_Skor", "Ort_Getiri"])
        fig.update_layout(height=300, showlegend=False, margin=dict(t=40, b=10))
        st.plotly_chart(fig, width="stretch")

# ── İzleme listesi ─────────────────────────────────────────────────────────────
watch = decision[decision.get("Izleme_Listesi_Adayi", False).fillna(False)] \
    if "Izleme_Listesi_Adayi" in decision.columns else pd.DataFrame()
if not watch.empty:
    st.divider()
    st.subheader("İzleme listesi adayları (kısa geçmiş — ana öneri dışı)")
    wcols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                         "Veri_Noktasi_Sayisi", "Karar_Bayraklari"] if c in watch.columns]
    st.dataframe(_safe_top(watch, "Overall_Score", 12)[wcols], width="stretch",
                 hide_index=True, column_config=ui.metric_column_config())

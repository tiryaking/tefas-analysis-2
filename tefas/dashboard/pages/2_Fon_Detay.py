"""Fon Detay: tek fonun buyumesi, drawdown'u, yuvarlanan metrikleri ve kunyesi.

Grafik verileri PDF ile AYNI `charts.prep_*` fonksiyonlarindan gelir - web ile
rapor ayni sayilari gosterir; yalnizca cizici farkli (Plotly  matplotlib).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas import charts
from tefas.dashboard import data

st.set_page_config(page_title="Fon Detay", page_icon=":microscope:", layout="wide")
ft = data.sidebar_fund_type()
st.title("Fon Detay")

scored = data.load_scored(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty or combined is None:
    data.no_data_warning(ft)
    st.stop()

labels = {str(r["Fon Kodu"]): f"{r['Fon Kodu']} - {str(r['Fon Adi'])[:60]}"
          for _, r in scored.iterrows()}
default_code = scored.nlargest(1, "Overall_Score")["Fon Kodu"].iloc[0]
code = st.selectbox("Fon sec", sorted(labels), index=sorted(labels).index(str(default_code)),
                    format_func=lambda c: labels[c])

row = scored[scored["Fon Kodu"].astype(str) == code].iloc[0]
st.caption(str(row["Fon Adi"]))

m1, m2, m3, m4, m5, m6 = st.columns(6)
num = lambda c: pd.to_numeric(pd.Series([row.get(c)]), errors="coerce").iloc[0]
m1.metric("Composite skor", f"{num('Overall_Score'):.1f}")
m2.metric("Yillik getiri", f"%{num('Yillik_Getiri'):.1f}")
m3.metric("Volatilite", f"%{num('Yillik_Volatilite'):.1f}")
m4.metric("Sharpe", f"{num('Sharpe_Orani'):.2f}")
m5.metric("Max drawdown", f"%{num('Max_Drawdown'):.1f}")
m6.metric("Tema", str(row.get("Tema", "-")))

sub = combined[combined["Fon Kodu"].astype(str) == code].sort_values("Tarih")
prices = pd.to_numeric(sub["Fiyat"], errors="coerce")
t = pd.to_datetime(sub["Tarih"])
mask = prices.notna() & (prices > 0)
prepped = charts.prep_drawdown(prices[mask])

if prepped is None:
    st.info("Bu fon icin yeterli fiyat gecmii yok (<10 gozlem).")
    st.stop()
norm, dd = prepped
tt = t[mask]

c_left, c_right = st.columns(2)
fig = go.Figure()
fig.add_scatter(x=tt, y=norm, mode="lines", name=code, line=dict(width=2))
fig.add_hline(y=100, line_dash="dot", line_color="grey")
fig.update_layout(title="Kumulatif Buyume (baz=100)", height=360,
                  yaxis_title="Deer", margin=dict(t=40, b=10))
c_left.plotly_chart(fig, width="stretch")

fig_dd = go.Figure()
fig_dd.add_scatter(x=tt, y=-dd, mode="lines", fill="tozeroy", name="Drawdown",
                   line=dict(color="#c0392b", width=1))
fig_dd.update_layout(title="Sualti / Drawdown (%)", height=360,
                     yaxis_title="Zirveye gore kayip (%)", margin=dict(t=40, b=10))
c_right.plotly_chart(fig_dd, width="stretch")

#  Yuvarlanan 63 gunluk getiri & volatilite (paylailan prep_rolling) 
pivot = charts.price_pivot(sub)
rolled = charts.prep_rolling(pivot, [code])
if rolled is not None:
    roll_ret, roll_vol = rolled
    r1, r2 = st.columns(2)
    f1 = go.Figure()
    f1.add_scatter(x=roll_ret.index, y=roll_ret[code], mode="lines", name="63g getiri")
    f1.update_layout(title="Yuvarlanan 63g Getiri (yillik, %)", height=320, margin=dict(t=40, b=10))
    r1.plotly_chart(f1, width="stretch")
    f2 = go.Figure()
    f2.add_scatter(x=roll_vol.index, y=roll_vol[code], mode="lines", name="63g vol",
                   line=dict(color="#bf8410"))
    f2.update_layout(title="Yuvarlanan 63g Volatilite (%)", height=320, margin=dict(t=40, b=10))
    r2.plotly_chart(f2, width="stretch")

#  Aylik getiriler (paylailan prep_monthly_returns) 
monthly = charts.prep_monthly_returns(pivot)
if not monthly.empty and code in monthly.columns:
    mr = monthly[code].dropna()
    fig_m = go.Figure()
    fig_m.add_bar(x=[str(p) for p in mr.index], y=mr.values,
                  marker_color=["#0f8a6a" if v >= 0 else "#c0392b" for v in mr.values])
    fig_m.update_layout(title="Aylik Getiriler (%)", height=300, margin=dict(t=40, b=10))
    st.plotly_chart(fig_m, width="stretch")

with st.expander("Tum metrikler"):
    metrics_table = row.to_frame("Deer").astype(str)
    st.dataframe(metrics_table, width="stretch")


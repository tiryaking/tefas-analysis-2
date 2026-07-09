"""Fon Detay: tek fonun künyesi, gerekçesi, akran kıyası, büyüme/drawdown/
rolling grafikleri ve skor geçmişi.

Grafik verileri PDF ile AYNI `charts.prep_*` fonksiyonlarından gelir — web ile
rapor aynı sayıları gösterir; yalnızca çizici farklı (Plotly ↔ matplotlib).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tefas import charts, config, narrative, themes
from tefas.dashboard import data, figures, ui

ft = data.sidebar_fund_type()
st.title("Fon Detay")

scored = data.enriched_frame(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty or combined is None:
    data.no_data_warning(ft)
    st.stop()

labels = ui.fund_label_map(scored)
default_code = scored.nlargest(1, "Overall_Score")["Fon Kodu"].iloc[0]
code = st.selectbox("Fon seç", sorted(labels),
                    index=sorted(labels).index(str(default_code)),
                    format_func=lambda c: labels[c])

row = scored[scored["Fon Kodu"].astype(str) == code].iloc[0]
st.caption(str(row["Fon Adi"]))
st.info("💡 " + narrative.build_rationale(row))

# ── Tear-sheet metrik kartları ────────────────────────────────────────────────
num = lambda c: pd.to_numeric(pd.Series([row.get(c)]), errors="coerce").iloc[0]
r1 = st.columns(6)
r1[0].metric("Composite skor", narrative.fmt(num("Overall_Score"), 1))
r1[1].metric("Yıllık getiri", narrative.pct(num("Yillik_Getiri")))
r1[2].metric("Volatilite", narrative.pct(num("Yillik_Volatilite")))
r1[3].metric("Sharpe", narrative.fmt(num("Sharpe_Orani"), 2))
r1[4].metric("Sortino", narrative.fmt(num("Sortino_Orani"), 2))
r1[5].metric("Tema", str(row.get("Tema", "-")))
r2 = st.columns(6)
r2[0].metric("Max drawdown", narrative.pct(num("Max_Drawdown")))
r2[1].metric("Calmar", narrative.fmt(num("Calmar_Orani"), 2))
r2[2].metric("VaR %95", narrative.pct(num("VaR_95")))
r2[3].metric("CVaR %95", narrative.pct(num("CVaR_95")))
r2[4].metric("Reel getiri", narrative.pct(num("Reel_Getiri_1Y")))
r2[5].metric("AUM (mn TL)", narrative.fmt(num("Fon_Toplam_Deger_Milyon_TL"), 0))

# ── Tarih aralığı (grafik verilerini dilimler) ────────────────────────────────
sub = combined[combined["Fon Kodu"].astype(str) == code].sort_values("Tarih").copy()
sub["Tarih"] = pd.to_datetime(sub["Tarih"])
rng = None
if len(sub) > 2:
    lo, hi = sub["Tarih"].min().to_pydatetime(), sub["Tarih"].max().to_pydatetime()
    if lo < hi:
        rng = st.slider("Tarih aralığı", min_value=lo, max_value=hi, value=(lo, hi),
                        format="YYYY-MM-DD", key="detay_range")
if rng:
    sub = sub[(sub["Tarih"] >= pd.Timestamp(rng[0])) & (sub["Tarih"] <= pd.Timestamp(rng[1]))]

prices = pd.to_numeric(sub["Fiyat"], errors="coerce")
mask = prices.notna() & (prices > 0)
prepped = charts.prep_drawdown(prices[mask])
if prepped is None:
    st.info("Seçili aralıkta yeterli fiyat geçmişi yok (<10 gözlem).")
    st.stop()
norm, dd = prepped
tt = pd.to_datetime(sub["Tarih"])[mask]

# ── Büyüme (akran medyanı çizgili) + sualtı ───────────────────────────────────
theme = row.get("Tema")
peers = scored.loc[scored["Tema"] == theme, "Fon Kodu"].astype(str).tolist() \
    if "Tema" in scored.columns and pd.notna(theme) else []
bench, blabel = None, "Evren medyanı"
if len(peers) >= config.THEME_MIN_FUNDS:
    bench = themes.theme_median_growth(combined, codes=peers)
    blabel = f"Tema medyanı ({len(peers)} fon)"
else:
    bench = themes.theme_median_growth(combined)

norm_df = pd.DataFrame({code: norm}, index=tt)
c_left, c_right = st.columns(2)
c_left.plotly_chart(figures.fig_growth(norm_df, benchmark=bench, benchmark_label=blabel,
                                       title="Kümülatif Büyüme (baz=100)"), width="stretch")
fig_dd = go.Figure()
fig_dd.add_scatter(x=tt, y=-dd, mode="lines", fill="tozeroy", name="Drawdown",
                   line=dict(color="#c0392b", width=1))
# Sıfır referansını her zaman göster: sığ drawdown'lu fonlarda otomatik eksen
# 0'ı kesip grafiği "asılı" gösteriyordu.
fig_dd.update_yaxes(rangemode="tozero")
fig_dd.update_layout(title="Sualtı / Drawdown (%)", height=380,
                     yaxis_title="Zirveye göre kayıp (%)", margin=dict(t=40, b=10))
c_right.plotly_chart(fig_dd, width="stretch")

# ── Yuvarlanan metrikler + aylık getiriler (paylaşılan prep) ──────────────────
pivot = charts.price_pivot(sub)
rolled = charts.prep_rolling(pivot, [code])
if rolled is not None:
    roll_ret, roll_vol = rolled
    st.plotly_chart(figures.fig_rolling(roll_ret, roll_vol,
                                        rf=config.macro().risk_free_rate), width="stretch")

monthly = charts.prep_monthly_returns(pivot)
if not monthly.empty and code in monthly.columns:
    mr = monthly[code].dropna()
    fig_m = go.Figure()
    fig_m.add_bar(x=[str(p) for p in mr.index], y=mr.values,
                  marker_color=["#0f8a6a" if v >= 0 else "#c0392b" for v in mr.values])
    fig_m.update_layout(title="Aylık Getiriler (%)", height=300, margin=dict(t=40, b=10))
    st.plotly_chart(fig_m, width="stretch")

# ── Akran kıyas tablosu (fon vs tema medyanı vs evren medyanı) ────────────────
peer_cols = [("Yıllık Getiri", "Yillik_Getiri"), ("Volatilite", "Yillik_Volatilite"),
             ("Sharpe", "Sharpe_Orani"), ("Sortino", "Sortino_Orani"),
             ("Max Drawdown", "Max_Drawdown"), ("VaR %95", "VaR_95"),
             ("Reel Getiri", "Reel_Getiri_1Y"), ("AUM (mn TL)", "Fon_Toplam_Deger_Milyon_TL")]
if "Tema" in scored.columns:
    theme_meds = themes.theme_medians(scored, [c for _, c in peer_cols])
    tmed = theme_meds.loc[theme] if (theme_meds is not None and theme in theme_meds.index) else None
    peer_rows = []
    for label, col in peer_cols:
        peer_rows.append({
            "Metrik": label,
            "Fon": narrative.fmt(row.get(col), 2),
            "Tema Medyanı": narrative.fmt(tmed.get(col), 2) if tmed is not None and col in tmed.index else "—",
            "Evren Medyanı": narrative.fmt(pd.to_numeric(scored[col], errors="coerce").median(), 2)
            if col in scored.columns else "—",
        })
    st.subheader("Akran Kıyası")
    st.dataframe(pd.DataFrame(peer_rows), width="stretch", hide_index=True)

# ── Skor geçmişi zaman çizgisi ────────────────────────────────────────────────
hist = data.load_history(ft)
if hist is not None and not hist.empty:
    fh = hist[hist["Fon Kodu"].astype(str) == code].copy()
    n_snap = fh["Tarih"].nunique()
    st.subheader("Skor Geçmişi")
    if n_snap < 2:
        st.info("Trend için en az 2 anlık kayıt gerekli — her `tefas run` bir kayıt "
                "ekler; henüz yeterli geçmiş birikmedi.")
    else:
        fh["Tarih"] = pd.to_datetime(fh["Tarih"])
        fig_h = px.line(fh.sort_values("Tarih"), x="Tarih",
                        y=["Overall_Score", "Overall_Persentil"], markers=True,
                        labels={"value": "Skor / Persentil (0–100)", "variable": ""})
        # 0–100 sabit eksen: skor/persentil zaten bu ölçekte; otomatik sıkıştırma
        # tepe fonlarda sabit yüksek değeri "boş düz çizgi" gibi göstermesin.
        fig_h.update_yaxes(range=[0, 100])
        fig_h.update_layout(height=320, margin=dict(t=20, b=10),
                            legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_h, width="stretch")
        st.caption(f"{n_snap} anlık kayıt · Persentil = fonun evren içindeki sıra yüzdeliği "
                   "(100 = en tepe). Tepe fonlarda çizgiler yüksekte ve düz seyreder — bu "
                   "istikrar demektir, veri eksikliği değil.")

with st.expander("Tüm metrikler"):
    st.dataframe(row.to_frame("Değer").astype(str), width="stretch")

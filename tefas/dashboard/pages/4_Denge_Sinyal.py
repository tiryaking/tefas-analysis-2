"""Denge & Sinyal: model portföy sapması, rebalans önerileri, risk katkıları,
skor sinyalleri — CLI `tefas holdings check` ile aynı mantık, aynı modüller."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas import allocation, config, holdings, portfolio as pf
from tefas.dashboard import data

st.set_page_config(page_title="Denge & Sinyal", page_icon="⚖️", layout="wide")
ft = data.sidebar_fund_type()
st.title("Denge & Sinyal")
st.caption("Model portföy kantitatif bir örnektir; yatırım tavsiyesi değildir.")

scored = data.load_scored(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty or combined is None:
    data.no_data_warning(ft)
    st.stop()
if not config.DEFAULT_TRANSACTIONS_PATH.exists():
    st.info("İşlem defteri yok — önce **Portföyüm** sayfasından pozisyonlarınızı girin.")
    st.stop()

try:
    txns = holdings.load_transactions(config.DEFAULT_TRANSACTIONS_PATH)
except (ValueError, FileNotFoundError) as e:
    st.error(str(e))
    st.stop()
val = holdings.valuation(holdings.positions(txns), combined)
open_pos = val[val["Adet"] > 0]
if open_pos.empty:
    st.info("Açık pozisyon yok.")
    st.stop()

total_value = float(open_pos["Deger"].sum())
current_weights = {str(r["Fon Kodu"]): float(r["Agirlik"]) * 100
                   for _, r in open_pos.iterrows()}

elig = scored[scored["Uygun"]] if "Uygun" in scored.columns else scored
model = allocation.build_portfolio(elig if not elig.empty else scored)
model_weights = {str(p["Fon Kodu"]): float(p["Agirlik"]) for p in model}

# ── Ağırlık kıyası ───────────────────────────────────────────────────────────
all_codes = sorted(set(current_weights) | set(model_weights))
fig = go.Figure()
fig.add_bar(name="Mevcut", x=all_codes,
            y=[current_weights.get(c, 0.0) for c in all_codes], marker_color="#1f5fb0")
fig.add_bar(name="Model", x=all_codes,
            y=[model_weights.get(c, 0.0) for c in all_codes], marker_color="#0f8a6a")
fig.update_layout(barmode="group", title="Mevcut vs Model Ağırlıklar (%)",
                  height=380, margin=dict(t=40, b=10))
st.plotly_chart(fig, use_container_width=True)

# ── Rebalans önerileri ───────────────────────────────────────────────────────
st.subheader("Rebalans önerileri")
suggestions = allocation.rebalance(current_weights, model, total_value)
if not suggestions:
    st.success("Portföy model dağılıma yeterince yakın (eşik: 5 puan) — işlem önerisi yok.")
else:
    st.dataframe(pd.DataFrame(suggestions), use_container_width=True, hide_index=True,
                 column_config={"Tutar_TL": st.column_config.NumberColumn("Tutar (TL)", format="%.0f")})
    st.caption("Öneriler kendi kendini finanse eder: satışlar + alımlar ≈ 0 TL.")

# ── Risk katkıları ───────────────────────────────────────────────────────────
st.subheader("Gerçek portföyün risk profili")
port = [{"Fon Kodu": c, "Agirlik": w} for c, w in current_weights.items()]
risk = pf.portfolio_risk(combined, port)
if risk is None:
    st.info("Kovaryans hesaplanamadı (yetersiz ortak veri).")
else:
    r1, r2, r3 = st.columns(3)
    r1.metric("Portföy volatilitesi", f"%{risk['portfolio_vol']:.1f}")
    r2.metric("Çeşitlendirme kazancı", f"%{risk['diversification_gain']:.1f}")
    r3.metric("Ort. ikili korelasyon", f"{risk['avg_correlation']:.2f}")
    rc = risk.get("risk_contributions") or {}
    if rc:
        codes = list(rc)
        fig_rc = go.Figure()
        fig_rc.add_bar(name="Ağırlık", x=codes,
                       y=[risk["weights"].get(c, 0) * 100 for c in codes], marker_color="#1f5fb0")
        fig_rc.add_bar(name="Risk katkısı", x=codes,
                       y=[rc[c] * 100 for c in codes], marker_color="#c0622d")
        fig_rc.update_layout(barmode="group", title="Ağırlık vs Gerçek Risk Katkısı (%)",
                             height=340, margin=dict(t=40, b=10))
        st.plotly_chart(fig_rc, use_container_width=True)

# ── Sinyaller ────────────────────────────────────────────────────────────────
st.subheader("Sinyaller")
history = data.load_history(ft)
sigs = holdings.signals(list(current_weights), scored, history)
if not sigs:
    st.success("Sinyal yok — pozisyonlar skor tablosunda ve trend stabil.")
for s in sigs:
    (st.warning if s["Tip"] == "UYARI" else st.info)(f"**{s['Fon Kodu']}** — {s['Mesaj']}")

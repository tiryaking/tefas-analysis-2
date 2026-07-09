"""Model & Metodoloji: walk-forward doğrulama, model ağırlıkları, config'den
üretilen metodoloji ve skor geçmişi trend keşfi (PDF'in gösteremediği zaman
boyutu)."""
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

from tefas import model_config, narrative
from tefas.dashboard import data, ui

st.set_page_config(page_title="Model & Metodoloji", page_icon=":scroll:", layout="wide")
ft = data.sidebar_fund_type()
st.title("Model & Metodoloji")

model_cfg = model_config.current()
st.caption(f"Aktif model: **{model_cfg.version}** · kaynak: {model_cfg.source}")

tab_val, tab_weights, tab_method, tab_history = st.tabs(
    ["Walk-Forward Doğrulama", "Model Ağırlıkları", "Metodoloji", "Skor Geçmişi"])

# ── Walk-forward doğrulama ─────────────────────────────────────────────────────
with tab_val:
    vs = data.load_validation(ft)
    if vs.available:
        v = vs.table.copy()
        st.dataframe(v, width="stretch", hide_index=True)
        fig = go.Figure()
        fig.add_bar(name="Ort. fark", x=v["Ufuk_Ay"].astype(str), y=v["Ort_Fark"],
                    marker_color="#1f5fb0")
        fig.add_scatter(name="İsabet", x=v["Ufuk_Ay"].astype(str), y=v["Isabet_Orani"] * 100,
                        yaxis="y2", mode="lines+markers", marker_color="#0f8a6a")
        fig.update_layout(height=420, xaxis_title="Ufuk (ay)", yaxis_title="Fark (%)",
                          yaxis2=dict(title="İsabet %", overlaying="y", side="right", range=[0, 100]),
                          margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")
        st.caption("Model her ay sonunda yalnızca o güne kadarki veriyle seçim yapsaydı "
                   "sonraki dönemde evren ortalamasını aşar mıydı? Kat sayısı az; "
                   "istatistiksel kanıt değil, yön sağlamasıdır.")
    else:
        st.warning(vs.message)

# ── Model ağırlıkları ──────────────────────────────────────────────────────────
with tab_weights:
    st.subheader("Composite skor ağırlıkları")
    ow = pd.DataFrame([{"Bileşen": k, "Ağırlık %": v * 100}
                       for k, v in model_cfg.overall_weights.items()]).sort_values("Ağırlık %")
    st.plotly_chart(px.bar(ow, x="Ağırlık %", y="Bileşen", orientation="h", text="Ağırlık %")
                    .update_layout(height=320, margin=dict(t=10, b=10)), width="stretch")
    st.subheader("Profil ağırlıkları")
    for prof, weights in model_cfg.profile_weights.items():
        pw = pd.DataFrame([{"Bileşen": k, "Ağırlık %": v * 100} for k, v in weights.items()])
        st.markdown(f"**{prof}** — " + ", ".join(f"{r['Bileşen']} %{r['Ağırlık %']:g}"
                                                  for _, r in pw.iterrows()))
    st.subheader("Öneri ayarları")
    st.json(model_cfg.recommendation_settings)

# ── Metodoloji (config'den üretilir) ───────────────────────────────────────────
with tab_method:
    st.caption("Bu metinler doğrudan aktif model ağırlıklarından ve config "
               "sabitlerinden üretilir — ayarlar değişince metin de değişir.")
    for title, body in narrative.methodology_sections(model_cfg):
        with st.expander(title, expanded=False):
            st.markdown(body)

# ── Skor geçmişi trendi ────────────────────────────────────────────────────────
with tab_history:
    hist = data.load_history(ft)
    if hist is None or hist.empty:
        st.info("Skor geçmişi henüz birikmedi — birkaç `tefas run` sonra dolacak.")
    elif hist["Tarih"].nunique() < 2:
        st.info("Trend için en az 2 farklı tarih gerekli (şu an "
                f"{hist['Tarih'].nunique()}). Birkaç `tefas run` daha bekleyin.")
    else:
        hist = hist.copy()
        hist["Tarih"] = pd.to_datetime(hist["Tarih"])
        dates = sorted(hist["Tarih"].unique())
        last, prev = dates[-1], dates[-2]
        cur = hist[hist["Tarih"] == last].set_index("Fon Kodu")["Overall_Persentil"]
        old = hist[hist["Tarih"] == prev].set_index("Fon Kodu")["Overall_Persentil"]
        delta = (cur - old).dropna().sort_values()
        movers = pd.concat([
            delta.tail(8).rename("Değişim").reset_index().assign(Yön="Yükselen"),
            delta.head(8).rename("Değişim").reset_index().assign(Yön="Düşen"),
        ])
        st.subheader(f"En çok hareket edenler ({prev.date()} → {last.date()}, persentil puanı)")
        st.plotly_chart(px.bar(movers, x="Değişim", y="Fon Kodu", color="Yön",
                               orientation="h", color_discrete_map={"Yükselen": "#0f8a6a",
                                                                    "Düşen": "#c0392b"})
                        .update_layout(height=460, margin=dict(t=10, b=10)), width="stretch")

        st.subheader("Fon skor zaman çizgisi")
        codes = sorted(hist["Fon Kodu"].unique())
        sel = st.multiselect("Fonlar", codes, default=list(delta.tail(3).index),
                             key="hist_codes")
        if sel:
            sub = hist[hist["Fon Kodu"].isin(sel)]
            st.plotly_chart(px.line(sub, x="Tarih", y="Overall_Score", color="Fon Kodu",
                                    markers=True).update_layout(height=380, margin=dict(t=10, b=10)),
                            width="stretch")
        ui.download_df(hist, f"skor_gecmisi_{ft.lower()}.csv", key="dl_hist")

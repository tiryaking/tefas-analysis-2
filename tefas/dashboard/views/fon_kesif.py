"""Fon Kesif: skorlu evreni tema/skor/AUM/arama ile filtrele; risk-getiri haritasi."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from tefas.dashboard import data, ui

ft = data.sidebar_fund_type()
st.title("Fon Keşif")

scored = data.load_scored(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

df = data.enriched_frame(ft)
for col in ["Overall_Score", "Yillik_Getiri", "Yillik_Volatilite", "Sharpe_Orani",
            "Max_Drawdown", "Fon_Toplam_Deger_Milyon_TL", "VaR_95", "Reel_Getiri_1Y"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

#  Filtreler
fc1, fc2, fc3, fc4, fc5 = st.columns([2, 1, 1, 1, 1])
# Karşılaştırma sayfasından `?tema=` linkiyle gelen ön-filtre
qp_tema = st.query_params.get("tema")
search = fc1.text_input("Ara (kod veya ad)", "")
temalar = sorted(df["Tema"].dropna().unique()) if "Tema" in df.columns else []
sel_temalar = fc2.multiselect("Tema", temalar,
                              default=[qp_tema] if qp_tema in temalar else [])
min_skor = fc3.slider("Min. skor", 0, 100, 0, 5)
max_dd = fc4.slider("Maks. drawdown", 0, 80, 80, 5)
min_aum = fc5.number_input("Min. AUM (mn TL)", min_value=0.0, value=0.0, step=50.0)
only_elig = st.checkbox("Yalnızca ana öneri evreni", value=True)

mask = pd.Series(True, index=df.index)
if search.strip():
    s = search.strip().upper()
    mask &= (df["Fon Kodu"].astype(str).str.upper().str.contains(s, regex=False)
             | df["Fon Adi"].astype(str).str.upper().str.contains(s, regex=False))
if sel_temalar:
    mask &= df["Tema"].isin(sel_temalar)
mask &= df["Overall_Score"].fillna(0) >= min_skor
if "Max_Drawdown" in df.columns:
    mask &= df["Max_Drawdown"].fillna(999) <= max_dd
if min_aum > 0 and "Fon_Toplam_Deger_Milyon_TL" in df.columns:
    mask &= df["Fon_Toplam_Deger_Milyon_TL"].fillna(0) >= min_aum
if only_elig and "Oneri_Uygun" in df.columns:
    mask &= df["Oneri_Uygun"].fillna(False)

flt = df[mask].sort_values("Overall_Score", ascending=False)
st.caption(f"{len(flt)} / {len(df)} fon gösteriliyor.")

cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score",
                    "Yillik_Getiri", "Yillik_Volatilite", "Sharpe_Orani", "Sortino_Orani",
                    "Max_Drawdown", "VaR_95", "Reel_Getiri_1Y", "Fon_Toplam_Deger_Milyon_TL",
                    "Rf_Ustu", "Karar_Bayraklari"] if c in flt.columns]
st.dataframe(flt[cols], width="stretch", hide_index=True, height=460,
             column_config=ui.metric_column_config())
ui.download_df(flt[cols], f"fon_kesif_{ft.lower()}.csv", key="dl_kesif")

#  Risk-getiri haritasi
st.subheader("Risk – Getiri Haritası")
plot_df = flt.dropna(subset=["Yillik_Volatilite", "Yillik_Getiri"])
if len(plot_df) >= 3:
    # PDF ile ayni mantik: eksenler 1.-99. yuzdelie kirpilir ki uc deerler haritayi ezmesin
    x, y = plot_df["Yillik_Volatilite"], plot_df["Yillik_Getiri"]
    fig = px.scatter(plot_df, x="Yillik_Volatilite", y="Yillik_Getiri",
                     color="Tema" if "Tema" in plot_df.columns else None,
                     size="Fon_Toplam_Deger_Milyon_TL" if "Fon_Toplam_Deger_Milyon_TL" in plot_df.columns else None,
                     size_max=18, hover_name="Fon Kodu",
                     hover_data={"Fon Adi": True, "Overall_Score": ":.1f",
                                 "Sharpe_Orani": ":.2f"},
                     labels={"Yillik_Volatilite": "Yillik Volatilite (%)",
                             "Yillik_Getiri": "Yillik Getiri (%)"})
    fig.update_xaxes(range=[max(0, x.quantile(0.01) - 2), x.quantile(0.99) + 2])
    fig.update_yaxes(range=[y.quantile(0.01) - 5, y.quantile(0.99) + 5])
    fig.update_layout(height=520, legend_title_text="Tema")
    st.plotly_chart(fig, width="stretch")
else:
    st.info("Haritayi cizmek icin filtrede en az 3 fon kalmali.")


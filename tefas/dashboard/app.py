"""TEFAS Dashboard — genel bakış sayfası. `tefas dashboard` ile açılır."""
from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run` doğrudan bu dosyayı çalıştırır; paket kökünü path'e ekle.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from tefas import config
from tefas.dashboard import data

st.set_page_config(page_title="TEFAS Dashboard", page_icon="📈", layout="wide")

ft = data.sidebar_fund_type()
st.title("TEFAS Fon Analizi")
st.caption("Skorlar en son `tefas run` çıktısından okunur; bu panel yalnızca okur, "
           "pipeline'ı değiştirmez. Yatırım tavsiyesi değildir.")

scored = data.load_scored(ft)
if scored is None or scored.empty:
    data.no_data_warning(ft)
    st.stop()

combined = data.load_combined(ft)
as_of = pd.to_datetime(combined["Tarih"]).max().date() if combined is not None else "—"

elig = scored[scored["Uygun"]] if "Uygun" in scored.columns else scored
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Analiz edilen fon", f"{len(scored):,}")
c2.metric("Uygun (AUM/yaş)", f"{len(elig):,}")
c3.metric("Ort. yıllık getiri", f"%{pd.to_numeric(scored['Yillik_Getiri'], errors='coerce').mean():.1f}")
c4.metric("Ort. Sharpe", f"{pd.to_numeric(scored['Sharpe_Orani'], errors='coerce').mean():.2f}")
c5.metric("Veri sonu", str(as_of))

st.subheader("En iyi 10 fon — composite skor")
cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", "Overall_Score", "Yillik_Getiri",
                    "Yillik_Volatilite", "Sharpe_Orani", "Max_Drawdown",
                    "Fon_Toplam_Deger_Milyon_TL"] if c in elig.columns]
top10 = elig.nlargest(10, "Overall_Score")[cols].reset_index(drop=True)
st.dataframe(top10, use_container_width=True, hide_index=True,
             column_config={
                 "Overall_Score": st.column_config.ProgressColumn(
                     "Skor", min_value=0, max_value=100, format="%.1f"),
                 "Yillik_Getiri": st.column_config.NumberColumn("Yıl. Getiri %", format="%.1f"),
                 "Yillik_Volatilite": st.column_config.NumberColumn("Volatilite %", format="%.1f"),
                 "Sharpe_Orani": st.column_config.NumberColumn("Sharpe", format="%.2f"),
                 "Max_Drawdown": st.column_config.NumberColumn("Max DD %", format="%.1f"),
                 "Fon_Toplam_Deger_Milyon_TL": st.column_config.NumberColumn("AUM (mn TL)", format="%.0f"),
             })

st.info("Soldaki sayfalardan **Fon Keşif** ile evreni filtreleyin, **Fon Detay** ile "
        "tek fona inin, **Portföyüm** ile kendi pozisyonlarınızı takip edin, "
        "**Denge & Sinyal** ile model sapmasını görün.")

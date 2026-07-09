"""Yeniden kullanılabilir dashboard blokları.

`recommendation_group`: bir öneri grubunu (ana öneri veya bir risk profili)
PDF'teki gibi tam görselleştirir — gerekçeli TIKLANABİLİR tablo + yıllık getiri
barı + kümülatif büyüme (evren medyanına karşı) + aylık getiri ısı takvimi.
Aynı blok her grupta çağrılır; tıklanan fon Fon Detay sayfasına götürür.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from tefas import charts, narrative, themes
from tefas.dashboard import data, figures, ui


def recommendation_group(title: str, df: pd.DataFrame, ft: str,
                         combined: pd.DataFrame | None, *,
                         score_col: str = "Overall_Score", n: int = 10,
                         key: str, score_label: str = "Skor") -> None:
    """Bir öneri grubunu tam görselleştirir (tablo + 3 grafik)."""
    st.subheader(title)
    if df is None or df.empty:
        st.info("Bu grupta gösterilecek fon yok.")
        return
    grp = df.head(n).copy()
    grp["Gerekçe"] = grp.apply(narrative.build_rationale, axis=1)

    cols = [c for c in ["Fon Kodu", "Fon Adi", "Tema", score_col, "Yillik_Getiri",
                        "Yillik_Volatilite", "Sharpe_Orani", "Max_Drawdown",
                        "Reel_Getiri_1Y", "Karar_Bayraklari", "Gerekçe"]
            if c in grp.columns]
    cfg = {**ui.metric_column_config(),
           score_col: st.column_config.ProgressColumn(score_label, min_value=0,
                                                      max_value=100, format="%.1f"),
           "Gerekçe": st.column_config.TextColumn("Gerekçe", width="large")}
    st.caption("💡 Bir satıra tıklayınca fon detayına gider.")
    ui.clickable_fund_table(grp[cols], key=f"{key}_tbl", column_config=cfg)
    ui.download_df(grp[cols], f"{key}_{ft.lower()}.csv", key=f"{key}_dl")

    codes = grp["Fon Kodu"].astype(str).tolist()
    pivot = data.price_pivot(ft)
    monthly = data.monthly_returns(ft)

    # Benzersiz key'ler: aynı blok birden çok grupta çağrılınca çakışma olmasın.
    c1, c2 = st.columns(2)
    with c1:
        bar_df = grp.dropna(subset=["Yillik_Getiri"]).sort_values("Yillik_Getiri")
        if not bar_df.empty:
            fig = px.bar(bar_df, x="Yillik_Getiri", y="Fon Kodu", orientation="h",
                         text="Yillik_Getiri", title="Yıllık Getiri (%)")
            fig.update_traces(texttemplate="%{text:.0f}%", marker_color="#1f5fb0")
            fig.update_layout(height=360, showlegend=False, margin=dict(t=40, b=10))
            st.plotly_chart(fig, width="stretch", key=f"{key}_bar")
    with c2:
        if pivot is not None:
            bench = themes.theme_median_growth(combined) if combined is not None else None
            st.plotly_chart(figures.fig_growth(
                charts.prep_growth(pivot, codes[:5]), benchmark=bench,
                title="Kümülatif Büyüme (ilk 5, ortak dönem)"),
                width="stretch", key=f"{key}_growth")

    if monthly is not None and not monthly.empty:
        st.plotly_chart(figures.fig_monthly_heatmap(monthly, codes,
                        median_label="Evren medyanı"), width="stretch", key=f"{key}_hm")

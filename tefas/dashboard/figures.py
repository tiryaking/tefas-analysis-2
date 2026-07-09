"""
Paylaşılan Plotly figür üreticileri (saf; `streamlit` import ETMEZ).

Veri girer, `go.Figure` çıkar — birden çok sayfa (Detay, Karşılaştırma,
Portföy&Risk) aynı figürleri kopyalamasın. Grafikler `charts.prep_*`
çıktılarını tüketir (PDF ile web aynı sayıları gösterir) ve fon renkleri
`charts.FUND_PALETTE` ile tutarlıdır. Streamlit'siz olduğu için birim
testlenebilir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tefas import comparison
from tefas.charts import FUND_PALETTE

NAVY, GREEN, RUST, GREY = "#13294b", "#0f8a6a", "#c0622d", "#b8c1cf"
_MARGIN = dict(t=40, b=10, l=10, r=10)


def color_map(codes) -> dict[str, str]:
    """Fon → sabit renk (sıra bazlı; tüm figürlerde tutarlı)."""
    return {str(c): FUND_PALETTE[i % len(FUND_PALETTE)] for i, c in enumerate(codes)}


def _empty(msg: str = "Veri yetersiz") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(color=GREY, size=13))
    fig.update_layout(height=200, margin=_MARGIN,
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def fig_growth(norm_df: pd.DataFrame | None, cmap: dict | None = None,
               benchmark: pd.Series | None = None,
               benchmark_label: str = "Evren medyanı",
               title: str = "Kümülatif Büyüme (baz=100)") -> go.Figure:
    """`charts.prep_growth` çıktısı (baz-100, index=tarih, sütun=fon) → çizgi."""
    if norm_df is None or norm_df.empty:
        return _empty()
    cmap = cmap or color_map(norm_df.columns)
    fig = go.Figure()
    for c in norm_df.columns:
        fig.add_scatter(x=norm_df.index, y=norm_df[c], mode="lines", name=str(c),
                        line=dict(width=2, color=cmap.get(str(c))))
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index)
        b = b[(b.index >= norm_df.index[0]) & (b.index <= norm_df.index[-1])]
        if len(b) >= 2:
            b = b / b.iloc[0] * 100.0
            fig.add_scatter(x=b.index, y=b.values, mode="lines", name=benchmark_label,
                            line=dict(width=1.5, color=GREY, dash="dash"))
    fig.add_hline(y=100, line_dash="dot", line_color=GREY)
    fig.update_layout(title=title, height=380, margin=_MARGIN, yaxis_title="Değer",
                      legend=dict(orientation="h", y=-0.15))
    return fig


def fig_underwater(idx, cum, dd) -> go.Figure:
    """`portfolio.portfolio_drawdown` çıktısı → değer (üst) + sualtı (alt)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                        vertical_spacing=0.06)
    fig.add_scatter(x=idx, y=cum, mode="lines", name="Değer",
                    line=dict(color=NAVY, width=1.6), row=1, col=1)
    fig.add_hline(y=100, line_dash="dot", line_color=GREY, row=1, col=1)
    fig.add_scatter(x=idx, y=-np.asarray(dd), mode="lines", name="Drawdown",
                    fill="tozeroy", line=dict(color=RUST, width=1), row=2, col=1)
    fig.update_yaxes(title_text="Değer (100 taban)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown %", row=2, col=1)
    fig.update_layout(title="Portföy Değeri ve Sualtı (Drawdown)", height=460,
                      margin=_MARGIN, showlegend=False)
    return fig


def fig_drawdown_lines(pivot: pd.DataFrame, codes, cmap: dict | None = None) -> go.Figure:
    """Her fonun sualtı eğrisi tek eksende (dayanıklılık kıyası)."""
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return _empty()
    cmap = cmap or color_map(codes)
    fig = go.Figure()
    for c in avail:
        s = pivot[c].dropna()
        if len(s) < 10:
            continue
        p = s.to_numpy()
        peak = np.maximum.accumulate(p)
        dd = (peak - p) / peak * 100.0
        fig.add_scatter(x=s.index, y=-dd, mode="lines", name=str(c),
                        line=dict(width=1.3, color=cmap.get(str(c))))
    fig.add_hline(y=0, line_color=GREY)
    fig.update_layout(title="Sualtı (Drawdown) Karşılaştırması", height=360,
                      margin=_MARGIN, yaxis_title="Zirveye göre kayıp %",
                      legend=dict(orientation="h", y=-0.15))
    return fig


def fig_rolling(roll_ret: pd.DataFrame | None, roll_vol: pd.DataFrame | None,
                cmap: dict | None = None, rf: float | None = None) -> go.Figure:
    """`charts.prep_rolling` çıktısı → yuvarlanan getiri (üst) + volatilite (alt)."""
    if roll_ret is None or roll_ret.empty:
        return _empty()
    # Isınma dead-space'ini kırp: 63-günlük pencere ilk ~63 gözlemde hesaplanamaz
    # (baştan NaN). Grafik ilk geçerli değerden başlasın — sol üçte bir boş kalıp
    # rf çizgisi orada uzanarak "bozuk" görünmesin.
    valid = roll_ret.dropna(how="all")
    if valid.empty:
        return _empty("Yuvarlanan pencere için yeterli veri yok")
    start = valid.index[0]
    roll_ret = roll_ret.loc[start:]
    roll_vol = roll_vol.loc[start:] if roll_vol is not None else roll_vol
    cmap = cmap or color_map(roll_ret.columns)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45],
                        vertical_spacing=0.06,
                        subplot_titles=("63g Getiri (yıllık, %)", "63g Volatilite (%)"))
    for c in roll_ret.columns:
        col = cmap.get(str(c))
        fig.add_scatter(x=roll_ret.index, y=roll_ret[c], mode="lines", name=str(c),
                        line=dict(width=1.4, color=col), row=1, col=1)
        fig.add_scatter(x=roll_vol.index, y=roll_vol[c], mode="lines", name=str(c),
                        line=dict(width=1.4, color=col), showlegend=False, row=2, col=1)
    if rf:
        fig.add_hline(y=rf, line_dash="dash", line_color=GREY, row=1, col=1)
    fig.update_layout(height=480, margin=_MARGIN, legend=dict(orientation="h", y=-0.1))
    return fig


def fig_monthly_heatmap(monthly: pd.DataFrame | None, codes,
                        median_label: str = "Evren medyanı") -> go.Figure:
    """`charts.prep_monthly_returns` çıktısı → aylık getiri ısı haritası
    (fon × ay, 0 merkezli RdYlGn, medyan satırı en altta)."""
    if monthly is None or monthly.empty:
        return _empty()
    avail = [c for c in codes if c in monthly.columns]
    if not avail:
        return _empty()
    data = monthly[avail].T
    row_labels = list(avail)
    med = monthly.median(axis=1)
    data = pd.concat([data, med.to_frame(median_label).T])
    row_labels.append(median_label)
    vals = data.to_numpy(dtype=float)
    if not np.isfinite(vals).any():
        return _empty()
    lim = float(np.nanmax(np.abs(vals)))
    fig = go.Figure(go.Heatmap(
        z=vals, x=[str(p) for p in monthly.index], y=row_labels,
        colorscale="RdYlGn", zmid=0, zmin=-lim, zmax=lim,
        text=np.round(vals, 1), texttemplate="%{text}", textfont=dict(size=9),
        hovertemplate="%{y} · %{x}: %{z:.1f}%<extra></extra>"))
    fig.update_layout(title="Aylık Getiri Takvimi (%)", height=max(300, 34 * len(row_labels) + 120),
                      margin=_MARGIN)
    return fig


def fig_corr_heatmap(corr: pd.DataFrame | None) -> go.Figure:
    """Fonlar arası korelasyon ısı haritası."""
    if corr is None or corr.empty or corr.shape[0] < 2:
        return _empty("Korelasyon için en az 2 fon gerekli")
    fig = go.Figure(go.Heatmap(
        z=corr.to_numpy(), x=list(corr.columns), y=list(corr.index),
        colorscale="RdYlGn", zmin=-1, zmax=1, zmid=0,
        text=np.round(corr.to_numpy(), 2), texttemplate="%{text}",
        hovertemplate="%{y} · %{x}: %{z:.2f}<extra></extra>"))
    fig.update_layout(title="Korelasyon Matrisi", height=420, margin=_MARGIN)
    return fig


def fig_radar(met: pd.DataFrame) -> go.Figure:
    """Çok-boyutlu göreli karşılaştırma (comparison.prep_radar ile normalize)."""
    if met is None or met.empty:
        return _empty()
    labels, norm = comparison.prep_radar(met)
    cmap = color_map(met["Fon Kodu"].tolist())
    theta = labels + [labels[0]]
    fig = go.Figure()
    for i, (_, r) in enumerate(met.iterrows()):
        vals = norm[:, i].tolist()
        vals += vals[:1]
        code = str(r["Fon Kodu"])
        fig.add_scatterpolar(r=vals, theta=theta, name=code, fill="toself",
                             line=dict(color=cmap.get(code)), opacity=0.75)
    fig.update_layout(title="Çok-Boyutlu Karşılaştırma (göreli)", height=460,
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)),
                      margin=dict(t=60, b=40, l=40, r=40))
    return fig


def fig_period_bars(met: pd.DataFrame) -> go.Figure:
    """Dönemsel getiri (1A/3A/6A/1Y) — fon başına gruplanmış bar."""
    periods = [("1A", "Getiri_1A"), ("3A", "Getiri_3A"), ("6A", "Getiri_6A"), ("1Y", "Getiri_1Y")]
    have = [(lbl, col) for lbl, col in periods if col in met.columns]
    if not have:
        return _empty("Dönemsel getiri sütunları yok")
    cmap = color_map(met["Fon Kodu"].tolist())
    fig = go.Figure()
    for _, r in met.iterrows():
        code = str(r["Fon Kodu"])
        fig.add_bar(name=code, x=[lbl for lbl, _ in have],
                    y=[pd.to_numeric(r.get(col), errors="coerce") for _, col in have],
                    marker_color=cmap.get(code))
    fig.update_layout(barmode="group", title="Dönemsel Getiriler (%)", height=360,
                      margin=_MARGIN, legend=dict(orientation="h", y=-0.15))
    return fig


def fig_weight_vs_risk(risk: dict | None) -> go.Figure:
    """`portfolio.portfolio_risk` çıktısı → ağırlık vs gerçek risk katkısı."""
    if not risk:
        return _empty("Kovaryans hesaplanamadı")
    rc = risk.get("risk_contributions") or {}
    wt = risk.get("weights") or {}
    codes = list(rc)
    if not codes:
        return _empty()
    fig = go.Figure()
    fig.add_bar(name="Ağırlık", x=codes, y=[wt.get(c, 0) * 100 for c in codes],
                marker_color="#1f5fb0")
    fig.add_bar(name="Risk katkısı", x=codes, y=[rc.get(c, 0) * 100 for c in codes],
                marker_color=RUST)
    fig.update_layout(barmode="group", title="Ağırlık vs Gerçek Risk Katkısı (%)",
                      height=360, margin=_MARGIN, legend=dict(orientation="h", y=-0.15))
    return fig

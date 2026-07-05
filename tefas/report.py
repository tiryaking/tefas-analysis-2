"""
Konsolide premium PDF rapor.

FINDING #1 — v1 raporu CSV'leri diskten tekrar okuyordu. Burada `generate`
skorlu ve metrik DataFrame'leri doğrudan alır (in-process). Layout/charts v1 ile
aynı: kapak, yönetici özeti, en iyi fonlar, risk profilleri, örnek portföy,
risk-getiri haritası, metodoloji.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from adjustText import adjust_text
except ImportError:
    adjust_text = None

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import config, portfolio as pf

NAVY = colors.HexColor("#13294b")
BLUE = colors.HexColor("#1f5fb0")
LIGHT = colors.HexColor("#eef3fb")
LIGHTER = colors.HexColor("#f7f9fd")
GREY = colors.HexColor("#6b7785")
LINE = colors.HexColor("#d4dbe6")
MPL_NAVY, MPL_BLUE, MPL_GREEN, MPL_GREY = "#13294b", "#1f5fb0", "#0f8a6a", "#b8c1cf"
# Karşılaştırmada fon-başına tutarlı renkler (tüm grafiklerde aynı sıra).
FUND_PALETTE = ["#1f5fb0", "#0f8a6a", "#e0a526", "#c0622d", "#7d4fb0", "#2e86c1",
                "#c0392b", "#5d6d7e", "#16a085", "#8e44ad"]
GOOD = colors.HexColor("#e3f4ec")   # en-iyi hücre vurgusu (açık yeşil)


def _register_fonts():
    reg = "Helvetica"
    for fp in config.FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                pdfmetrics.registerFont(TTFont("TF", fp)); reg = "TF"; break
            except Exception:
                continue
    bold = reg
    for fp in config.BOLD_FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                pdfmetrics.registerFont(TTFont("TFB", fp)); bold = "TFB"; break
            except Exception:
                continue
    return reg, bold


FONT, BOLD = _register_fonts()


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("CoverTitle", fontName=BOLD, fontSize=30, leading=36, alignment=1, textColor=NAVY, spaceAfter=4))
    s.add(ParagraphStyle("CoverSub", fontName=FONT, fontSize=14, leading=19, alignment=1, textColor=BLUE, spaceAfter=2))
    s.add(ParagraphStyle("CoverInfo", fontName=FONT, fontSize=11, leading=17, alignment=1, textColor=GREY))
    s.add(ParagraphStyle("Section", fontName=BOLD, fontSize=17, leading=21, textColor=NAVY, spaceBefore=4, spaceAfter=8))
    s.add(ParagraphStyle("SubSec", fontName=BOLD, fontSize=12, leading=15, textColor=BLUE, spaceBefore=10, spaceAfter=4))
    s.add(ParagraphStyle("Body", fontName=FONT, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#2a2f36"), spaceAfter=4))
    s.add(ParagraphStyle("BodySm", fontName=FONT, fontSize=8.5, leading=12, textColor=GREY, spaceAfter=3))
    s.add(ParagraphStyle("Cell", fontName=FONT, fontSize=8, leading=10.5))
    s.add(ParagraphStyle("CellB", fontName=BOLD, fontSize=8, leading=10.5))
    s.add(ParagraphStyle("CellH", fontName=BOLD, fontSize=8, leading=10.5, textColor=colors.white))
    s.add(ParagraphStyle("Rationale", fontName=FONT, fontSize=8, leading=10.5, textColor=colors.HexColor("#33414f")))
    s.add(ParagraphStyle("Disclaimer", fontName=FONT, fontSize=7.5, leading=11, textColor=GREY))
    s.add(ParagraphStyle("CoverFilter", fontName=FONT, fontSize=7.5, leading=11, alignment=1, textColor=GREY))
    s.add(ParagraphStyle("KpiVal", fontName=BOLD, fontSize=18, leading=20, alignment=1, textColor=NAVY))
    s.add(ParagraphStyle("KpiLbl", fontName=FONT, fontSize=7.5, leading=9.5, alignment=1, textColor=GREY))
    s.add(ParagraphStyle("CardCode", fontName=BOLD, fontSize=11, leading=13, textColor=NAVY))
    s.add(ParagraphStyle("CardName", fontName=FONT, fontSize=7, leading=8.5, textColor=GREY))
    s.add(ParagraphStyle("CardKey", fontName=FONT, fontSize=7.5, leading=10, textColor=GREY))
    s.add(ParagraphStyle("CardVal", fontName=BOLD, fontSize=7.5, leading=10, textColor=colors.HexColor("#2a2f36")))
    return s


def fmt(x, dec=2, suffix="", dash="—"):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return dash
    try:
        return f"{float(x):,.{dec}f}{suffix}"
    except (ValueError, TypeError):
        return str(x)


def pct(x, dec=1):
    return fmt(x, dec, "%") if pd.notna(x) else "—"


def short_name(name, maxlen=46):
    s = str(name)
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def _code_label(row) -> str:
    """1 yıldan kısa fiyat geçmişi olan fonları '*' ile işaretler (#1)."""
    code = str(row["Fon Kodu"])
    n = row.get("Veri_Noktasi_Sayisi")
    if pd.notna(n) and n < config.TRADING_DAYS_PER_YEAR:
        return code + "*"
    return code


_THEMES = [
    ("Para Piyasası", ["PARA P", "KISA VADEL", "LIKIT"]),
    ("Borçlanma Araçları", ["BORCLANMA", "BORÇLANMA", "TAHVIL", "BONO", "EUROBOND"]),
    ("Kira Sertifikası", ["KIRA SERT", "SUKUK"]),
    ("Katılım", ["KATILIM", "PARTICIPATION"]),
    ("Hisse Senedi", ["HISSE", "HİSSE", "SENED", "EQUITY", "PAY"]),
    ("Teknoloji", ["TEKNOLOJ", "TEKNO", "TECH", "YAPAY ZEKA", "BILISIM"]),
    ("Altın & Kıymetli Maden", ["ALTIN", "GUMUS", "GÜMÜŞ", "GOLD", "KIYMETLI"]),
    ("Emtia & Enerji", ["EMTIA", "EMTİA", "ENERJ", "PETROL", "ENERGY"]),
    ("Yabancı / Endeks", ["YABANCI", "S&P", "SP500", "NASDAQ", "MSCI", "ENDEKS", "INDEX"]),
    ("Fon Sepeti", ["FON SEPET", "FUND OF"]),
    ("Karma / Değişken", ["KARMA", "DEGISKEN", "DEĞİŞKEN", "BALANCED", "SERBEST"]),
]


def fund_theme(name):
    if pd.isna(name):
        return "Diğer"
    up = str(name).upper()
    for theme, kws in _THEMES:
        if any(k in up for k in kws):
            return theme
    return "Diğer"


def build_rationale(row):
    bits = []
    sharpe = row.get("Sharpe_Orani")
    if pd.notna(sharpe):
        if sharpe >= 3:
            bits.append(f"çok güçlü risk-ayarlı getiri (Sharpe {fmt(sharpe,2)})")
        elif sharpe >= 1:
            bits.append(f"sağlam risk-ayarlı getiri (Sharpe {fmt(sharpe,2)})")
    vol = row.get("Yillik_Volatilite")
    if pd.notna(vol):
        if vol < 5:
            bits.append(f"çok düşük volatilite (%{fmt(vol,1)})")
        elif vol < 15:
            bits.append(f"düşük volatilite (%{fmt(vol,1)})")
        elif vol >= 30:
            bits.append(f"yüksek volatilite (%{fmt(vol,1)})")
    dd = row.get("Max_Drawdown")
    if pd.notna(dd) and dd < 5:
        bits.append(f"kontrollü kayıp (Max DD %{fmt(dd,1)})")
    ret = row.get("Yillik_Getiri")
    if pd.notna(ret) and ret >= 60:
        bits.append(f"yüksek yıllık getiri (%{fmt(ret,1)})")
    aum = row.get("Fon_Toplam_Deger_Milyon_TL")
    if pd.notna(aum) and aum >= config.AUM_BONUS_THRESHOLD:
        bits.append("güçlü büyüklük/likidite")
    if not bits:
        bits.append("dengeli genel profil")
    txt = "; ".join(bits[:3])
    return txt[0].upper() + txt[1:] + "."


def _make_table(headers, rows, col_widths, styles, align_right_from=2):
    data = [[Paragraph(h, styles["CellH"]) for h in headers]] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHTER]),
        ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
    ]))
    return t


def _chart(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def _chart_top_returns(df, path, n=12):
    d = df.nlargest(n, "Overall_Score").dropna(subset=["Yillik_Getiri"]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9.6, 4.2))
    bars = ax.barh(d["Fon Kodu"], d["Yillik_Getiri"], color=MPL_BLUE, alpha=0.9)
    ax.bar_label(bars, labels=[f"%{v:.0f}" for v in d["Yillik_Getiri"]], fontsize=7.5, padding=3, color=MPL_NAVY)
    ax.set_xlabel("Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("En İyi Fonlar — Yıllık Getiri", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.25, linestyle="--")
    ax.margins(x=0.12)
    return _chart(fig, path)


def _chart_allocation(portfolio, path):
    labels = [f"{p['Fon Kodu']}\n%{p['Agirlik']:.0f}" for p in portfolio]
    sizes = [p["Agirlik"] for p in portfolio]
    palette = ["#13294b", "#1f5fb0", "#2e86c1", "#0f8a6a", "#37a86b", "#e0a526", "#c0622d", "#7d4fb0", "#5d6d7e"]
    fig, ax = plt.subplots(figsize=(5.2, 4.2))
    wedges, _ = ax.pie(sizes, colors=(palette * 3)[: len(sizes)], startangle=90,
                       wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5))
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, frameon=False)
    ax.set_title("Önerilen Portföy Dağılımı", fontsize=11, color=MPL_NAVY, fontweight="bold")
    return _chart(fig, path)


def _chart_risk_return(df, highlight_codes, path):
    d = df.dropna(subset=["Yillik_Volatilite", "Yillik_Getiri"]).copy()
    if len(d) < 5:
        return None
    x, y = d["Yillik_Volatilite"], d["Yillik_Getiri"]
    xlo, xhi = np.percentile(x, 1), np.percentile(x, 99)
    ylo, yhi = np.percentile(y, 1), np.percentile(y, 99)
    xpad, ypad = (xhi - xlo) * 0.05 + 0.5, (yhi - ylo) * 0.05 + 0.5
    fig, ax = plt.subplots(figsize=(9.6, 4.5))
    ax.scatter(x, y, s=14, c=MPL_GREY, alpha=0.55, edgecolors="none", label="Tüm fonlar", zorder=1)
    hl = d[d["Fon Kodu"].isin(highlight_codes)].copy()
    ax.scatter(hl["Yillik_Volatilite"], hl["Yillik_Getiri"], s=70, c=MPL_GREEN,
               edgecolors="white", linewidths=0.8, label="Öne çıkan fonlar", zorder=3)
    x0, x1 = max(0, xlo - xpad), xhi + xpad
    y0, y1 = ylo - ypad, yhi + ypad
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    hl = hl[(hl["Yillik_Volatilite"].between(x0, x1)) & (hl["Yillik_Getiri"].between(y0, y1))]
    if len(hl) > 0:
        hl = hl.sort_values("Yillik_Getiri", ascending=False).reset_index(drop=True)
        n = len(hl)
        texts = []
        for i, (_, r) in enumerate(hl.iterrows()):
            t = ax.text(r["Yillik_Volatilite"], r["Yillik_Getiri"], str(r["Fon Kodu"]),
                        fontsize=7.5, color=MPL_NAVY, fontweight="bold",
                        ha="center", va="center", zorder=5,
                        bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=MPL_GREEN, lw=0.6, alpha=0.9))
            texts.append(t)
        if adjust_text and texts:
            adjust_text(texts, ax=ax, arrowprops=dict(arrowstyle="-", color=MPL_GREEN, lw=0.6, alpha=0.8))
    ax.set_xlabel("Yıllık Volatilite (%)", fontsize=9, color=MPL_NAVY)
    ax.set_ylabel("Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Risk – Getiri Haritası  (eksenler 1.–99. yüzdelik ile kırpıldı)", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.legend(fontsize=8, loc="lower right", framealpha=0.9)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    return _chart(fig, path)


def _chart_growth_history(combined, codes, path):
    if combined is None or not codes:
        return None
    pivot = combined.pivot_table(index="Tarih", columns="Fon Kodu", values="Fiyat", aggfunc="first").sort_index()
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return None
    pivot.index = pd.to_datetime(pivot.index)
    df = pivot[avail].dropna(how="any")
    if len(df) < 10:
        return None
    df_normalized = (df / df.iloc[0]) * 100
    fig, ax = plt.subplots(figsize=(9.6, 4.5))
    for c in avail:
        ax.plot(df_normalized.index, df_normalized[c], label=c, linewidth=1.5)
    ax.set_ylabel("Sermaye (Başlangıç = 100 TL)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Öne Çıkan Fonların Kümülatif Büyümesi", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, fontsize=8)
    ax.legend(fontsize=8, loc="upper left", framealpha=0.9)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    return _chart(fig, path)


def _chart_correlation_heatmap(combined, codes, path):
    if combined is None or len(codes) < 2:
        return None
    rets = pf.returns_matrix(combined, codes)
    if rets.shape[1] < 2:
        return None
    corr = rets.corr()
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    cax = ax.imshow(corr, cmap="RdYlGn", vmin=-1, vmax=1)
    ax.set_xticks(np.arange(len(corr.columns)))
    ax.set_yticks(np.arange(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(corr.columns, fontsize=8)
    for i in range(len(corr.columns)):
        for j in range(len(corr.columns)):
            val = corr.iloc[i, j]
            color = "white" if abs(val) > 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", color=color, fontsize=7)
    ax.set_title("Fonlar Arası Korelasyon Matrisi", fontsize=11, color=MPL_NAVY, fontweight="bold")
    fig.colorbar(cax, fraction=0.046, pad=0.04)
    return _chart(fig, path)


def _chart_distribution(df, top_codes, rf, path):
    """Evren dağılımı: yıllık getiri ve Sharpe histogramları + benchmark çizgileri."""
    d = df.copy()
    ret = pd.to_numeric(d["Yillik_Getiri"], errors="coerce").dropna()
    shp = pd.to_numeric(d["Sharpe_Orani"], errors="coerce").dropna()
    if len(ret) < 5:
        return None
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 3.05))
    # yıllık getiri
    rlo, rhi = np.percentile(ret, 1), np.percentile(ret, 99)
    ax1.hist(ret.clip(rlo, rhi), bins=40, color=MPL_BLUE, alpha=0.75, edgecolor="white", linewidth=0.3)
    for val, col, lbl in [(rf, MPL_GREY, f"rf %{rf:.0f}"),
                          (config.macro().inflation_rate, "#c0392b", f"TÜFE %{config.macro().inflation_rate:.0f}"),
                          (config.macro().policy_rate, "#e0a526", f"Politika %{config.macro().policy_rate:.0f}")]:
        if rlo <= val <= rhi:
            ax1.axvline(val, color=col, linestyle="--", linewidth=1.2, label=lbl)
    top_ret = pd.to_numeric(d[d["Fon Kodu"].isin(top_codes)]["Yillik_Getiri"], errors="coerce").dropna()
    for v in top_ret:
        ax1.axvline(min(max(v, rlo), rhi), color=MPL_GREEN, linewidth=0.8, alpha=0.9)
    ax1.set_title("Yıllık Getiri Dağılımı", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax1.set_xlabel("Yıllık Getiri (%)", fontsize=8, color=MPL_NAVY)
    ax1.set_ylabel("Fon sayısı", fontsize=8, color=MPL_NAVY)
    ax1.legend(fontsize=6.5, framealpha=0.9)
    # Sharpe
    if len(shp) >= 5:
        slo, shi = np.percentile(shp, 1), np.percentile(shp, 99)
        ax2.hist(shp.clip(slo, shi), bins=40, color="#0f8a6a", alpha=0.75, edgecolor="white", linewidth=0.3)
        ax2.axvline(float(shp.median()), color=MPL_GREY, linestyle="--", linewidth=1.2, label=f"medyan {shp.median():.2f}")
        top_shp = pd.to_numeric(d[d["Fon Kodu"].isin(top_codes)]["Sharpe_Orani"], errors="coerce").dropna()
        for v in top_shp:
            ax2.axvline(min(max(v, slo), shi), color=MPL_NAVY, linewidth=0.8, alpha=0.7)
        ax2.legend(fontsize=6.5, framealpha=0.9)
    ax2.set_title("Sharpe Oranı Dağılımı", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax2.set_xlabel("Sharpe", fontsize=8, color=MPL_NAVY)
    for ax in (ax1, ax2):
        ax.grid(True, axis="y", alpha=0.2, linestyle="--")
        ax.tick_params(labelsize=7)
        for sp in ax.spines.values():
            sp.set_color("#d4dbe6")
    fig.text(0.5, -0.02, "Yeşil/lacivert dikey çizgiler öne çıkan fonların konumu", ha="center", fontsize=7, color=MPL_GREY)
    fig.tight_layout()
    return _chart(fig, path)


def _chart_benchmark_bars(df, rf, path):
    """Evrenin benchmark'ları geçme oranları (yatay bar)."""
    n = len(df)
    if not n:
        return None
    ret = pd.to_numeric(df["Yillik_Getiri"], errors="coerce")
    real = pd.to_numeric(df.get("Reel_Getiri_1Y"), errors="coerce") if "Reel_Getiri_1Y" in df.columns else None
    items = [(f"Mevduat / rf (%{rf:.0f})", float((ret > rf).mean() * 100)),
             (f"Politika faizi (%{config.macro().policy_rate:.0f})", float((ret > config.macro().policy_rate).mean() * 100)),
             (f"Enflasyon (%{config.macro().inflation_rate:.0f})", float((ret > config.macro().inflation_rate).mean() * 100))]
    if real is not None:
        items.append(("Pozitif reel getiri", float((real > 0).mean() * 100)))
    labels = [i[0] for i in items][::-1]
    vals = [i[1] for i in items][::-1]
    fig, ax = plt.subplots(figsize=(9.6, 1.85))
    colors_ = ["#0f8a6a" if v >= 50 else ("#e0a526" if v >= 25 else "#c0392b") for v in vals]
    bars = ax.barh(labels, vals, color=colors_, alpha=0.9)
    ax.bar_label(bars, labels=[f"%{v:.0f}" for v in vals], fontsize=8, padding=3, color=MPL_NAVY)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Fonların yüzdesi (%)", fontsize=8, color=MPL_NAVY)
    ax.set_title("Analiz Evreni Benchmark'ları Ne Kadar Geçiyor?", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.2, linestyle="--")
    ax.tick_params(labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _chart_sparkline(combined, code, path):
    """Tek fon için kompakt tear-sheet grafiği: büyüme (üst) + sualtı/drawdown (alt)."""
    if combined is None:
        return None
    sub = combined[combined["Fon Kodu"] == code]
    if len(sub) < 10:
        return None
    sub = sub.sort_values("Tarih")
    p = pd.to_numeric(sub["Fiyat"], errors="coerce").to_numpy()
    t = pd.to_datetime(sub["Tarih"])
    if np.isnan(p).any() or p[0] <= 0:
        mask = (~np.isnan(p)) & (p > 0)
        p, t = p[mask], t[mask]
    if len(p) < 10:
        return None
    norm = p / p[0] * 100.0
    peak = np.maximum.accumulate(norm)
    dd = (peak - norm) / peak * 100.0
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(2.7, 1.35), height_ratios=[2, 1], sharex=True)
    a1.plot(t, norm, color=MPL_NAVY, linewidth=1.1)
    a1.fill_between(t, 100, norm, where=(norm >= 100), color=MPL_GREEN, alpha=0.12)
    a1.axhline(100, color=MPL_GREY, linewidth=0.5, linestyle=":")
    a2.fill_between(t, 0, dd, color="#c0392b", alpha=0.35, linewidth=0)
    a2.axhline(0, color=MPL_GREY, linewidth=0.5)
    a2.set_ylim(max(dd.max(), 0.5), 0)     # üstte 0, altta en derin drawdown; düz seride ince şerit
    for ax in (a1, a2):
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color("#d4dbe6"); sp.set_linewidth(0.4)
    fig.subplots_adjust(hspace=0.08, left=0.02, right=0.98, top=0.98, bottom=0.02)
    return _chart(fig, path)


def _chart_risk_contribution(risk, portfolio, path):
    """Fon başına ağırlık vs. gerçek risk katkısı (kovaryanstan)."""
    rc = risk.get("risk_contributions") or {}
    wts = risk.get("weights") or {}
    if not rc:
        return None
    codes = list(rc.keys())
    y = np.arange(len(codes))
    w_pct = [wts.get(c, 0) * 100 for c in codes]
    r_pct = [rc.get(c, 0) * 100 for c in codes]
    fig, ax = plt.subplots(figsize=(9.6, max(2.4, 0.5 * len(codes) + 1.2)))
    h = 0.38
    b1 = ax.barh(y - h / 2, w_pct, height=h, color=MPL_BLUE, alpha=0.85, label="Ağırlık")
    b2 = ax.barh(y + h / 2, r_pct, height=h, color="#c0622d", alpha=0.9, label="Risk katkısı")
    ax.bar_label(b1, labels=[f"%{v:.0f}" for v in w_pct], fontsize=7, padding=2, color=MPL_NAVY)
    ax.bar_label(b2, labels=[f"%{v:.0f}" for v in r_pct], fontsize=7, padding=2, color=MPL_NAVY)
    ax.set_yticks(y); ax.set_yticklabels(codes, fontsize=8)
    ax.set_xlabel("Portföy içindeki pay (%)", fontsize=8, color=MPL_NAVY)
    ax.set_title("Ağırlık vs. Gerçek Risk Katkısı", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.2, linestyle="--")
    ax.legend(fontsize=7.5, framealpha=0.9, loc="lower right")
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _chart_portfolio_underwater(combined, portfolio, path):
    """Örnek portföyün kümülatif değeri (üst) ve sualtı/drawdown eğrisi (alt)."""
    res = pf.portfolio_drawdown(combined, portfolio)
    if res is None:
        return None
    idx, cum, dd = res
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9.6, 4.0), height_ratios=[2, 1], sharex=True)
    a1.plot(idx, cum, color=MPL_NAVY, linewidth=1.4)
    a1.fill_between(idx, 100, cum, where=(cum >= 100), color=MPL_GREEN, alpha=0.12)
    a1.axhline(100, color=MPL_GREY, linewidth=0.6, linestyle=":")
    a1.set_ylabel("Değer (100 taban)", fontsize=8, color=MPL_NAVY)
    a1.set_title("Örnek Portföy — Kümülatif Değer ve Sualtı (Drawdown) Eğrisi", fontsize=10, color=MPL_NAVY, fontweight="bold")
    a2.fill_between(idx, 0, dd, color="#c0392b", alpha=0.35, linewidth=0)
    a2.plot(idx, dd, color="#c0392b", linewidth=0.8)
    a2.invert_yaxis()
    a2.set_ylabel("Drawdown (%)", fontsize=8, color=MPL_NAVY)
    import matplotlib.dates as mdates
    a2.xaxis.set_major_locator(mdates.AutoDateLocator())
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for ax in (a1, a2):
        ax.grid(True, alpha=0.2, linestyle="--")
        ax.tick_params(labelsize=7.5)
        for sp in ax.spines.values():
            sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _chart_category_mix(df, path, n=10):
    """Evrendeki tema dağılımı: fon sayısı (bar) + ortalama yıllık getiri (etiket)."""
    d = df.copy()
    d["_tema"] = d["Fon Adi"].map(fund_theme)
    grp = d.groupby("_tema").agg(n=("Fon Kodu", "count"),
                                 ret=("Yillik_Getiri", "mean")).sort_values("n", ascending=True)
    if grp.empty:
        return None
    grp = grp.tail(n)
    fig, ax = plt.subplots(figsize=(9.6, max(2.6, 0.45 * len(grp) + 1.0)))
    bars = ax.barh(grp.index, grp["n"], color=MPL_BLUE, alpha=0.85)
    labels = [f"{int(nn)} fon · ort. %{rr:.0f}" if pd.notna(rr) else f"{int(nn)} fon"
              for nn, rr in zip(grp["n"], grp["ret"])]
    ax.bar_label(bars, labels=labels, fontsize=7.5, padding=3, color=MPL_NAVY)
    ax.set_xlabel("Fon sayısı", fontsize=8, color=MPL_NAVY)
    ax.set_title("Kategori / Tema Dağılımı (analiz evreni)", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.2, linestyle="--")
    ax.margins(x=0.16)
    ax.tick_params(labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _build_portfolio(df):
    plan = [("Conservative", "Muhafazakâr", 2, 22.0), ("Balanced", "Dengeli", 2, 16.0),
            ("Moderate", "Orta", 1, 14.0), ("Aggressive", "Agresif", 1, 10.0)]
    portfolio, used_codes = [], set()
    for score_key, label, n_sel, weight in plan:
        col = f"{score_key}_Score"
        if col not in df.columns:
            continue
        used_themes, picked = set(), 0
        for _, r in df.sort_values(col, ascending=False).iterrows():
            if picked >= n_sel:
                break
            code, theme = r["Fon Kodu"], fund_theme(r["Fon Adi"])
            if code in used_codes or theme in used_themes:
                continue
            portfolio.append({"Fon Kodu": code, "Fon Adi": r["Fon Adi"], "Profil": label,
                              "Tema": theme, "Agirlik": weight, "Yillik_Getiri": r.get("Yillik_Getiri"),
                              "Yillik_Volatilite": r.get("Yillik_Volatilite"), "Sharpe_Orani": r.get("Sharpe_Orani")})
            used_codes.add(code); used_themes.add(theme); picked += 1
    total = sum(p["Agirlik"] for p in portfolio)
    if total > 0:
        for p in portfolio:
            p["Agirlik"] = p["Agirlik"] / total * 100.0
    return portfolio


def _portfolio_expected(portfolio):
    w = np.array([p["Agirlik"] / 100.0 for p in portfolio])
    r = np.array([p["Yillik_Getiri"] if pd.notna(p["Yillik_Getiri"]) else 0.0 for p in portfolio])
    v = np.array([p["Yillik_Volatilite"] if pd.notna(p["Yillik_Volatilite"]) else 0.0 for p in portfolio])
    return float(np.sum(w * r)), float(np.sqrt(np.sum((w * v) ** 2))), float(np.sum(w * v))


def _kpi_cards(pairs, styles, ncols=4, total_width=258 * mm):
    """(değer, etiket) çiftlerini kart ızgarasına çevirir (dashboard)."""
    cells = [[Paragraph(str(v), styles["KpiVal"]), Spacer(1, 1.5 * mm),
              Paragraph(lbl, styles["KpiLbl"])] for v, lbl in pairs]
    rows, cw = [], total_width / ncols
    for i in range(0, len(cells), ncols):
        chunk = cells[i:i + ncols]
        while len(chunk) < ncols:
            chunk.append([Spacer(1, 1)])
        rows.append(chunk)
    t = Table(rows, colWidths=[cw] * ncols)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _fund_card(row, spark_img, styles, rf):
    """Tek fon için mini tear-sheet kartı (metrik ızgarası + büyüme/drawdown sparkline)."""
    code = _code_label(row)
    theme = fund_theme(row.get("Fon Adi"))
    header = [[Paragraph(code, styles["CardCode"]), Paragraph(theme, styles["CardName"])]]
    htbl = Table(header, colWidths=[26 * mm, 60 * mm])
    htbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    name = Paragraph(short_name(row.get("Fon Adi"), 58), styles["CardName"])

    def kv(k, v):
        return [Paragraph(k, styles["CardKey"]), Paragraph(v, styles["CardVal"])]
    grid = [
        kv("Yıllık Getiri", pct(row.get("Yillik_Getiri"))) + kv("Volatilite", pct(row.get("Yillik_Volatilite"))),
        kv("Sharpe", fmt(row.get("Sharpe_Orani"), 2)) + kv("Sortino", fmt(row.get("Sortino_Orani"), 2)),
        kv("Max DD", pct(row.get("Max_Drawdown"))) + kv("Calmar", fmt(row.get("Calmar_Orani"), 2)),
        kv("VaR %95", pct(row.get("VaR_95"))) + kv("CVaR %95", pct(row.get("CVaR_95"))),
        kv("Reel Get.", pct(row.get("Reel_Getiri_1Y"))) + kv("Kuruluş CAGR", pct(row.get("Yillik_Getiri_Kurulus"))),
        kv("AUM (mn TL)", fmt(row.get("Fon_Toplam_Deger_Milyon_TL"), 0)) + kv("Yaş (yıl)", fmt(row.get("Fon_Yasi_Yil"), 1)),
    ]
    gtbl = Table(grid, colWidths=[18 * mm, 18 * mm, 18 * mm, 18 * mm])
    gtbl.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHTER]),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
    ]))
    inner = [htbl, name, Spacer(1, 1.5 * mm), gtbl]
    if spark_img:
        inner += [Spacer(1, 1.5 * mm), Image(spark_img, width=72 * mm, height=36 * mm)]
    card = Table([[inner]], colWidths=[80 * mm])
    card.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def generate(scored: pd.DataFrame, metrics: pd.DataFrame, fund_type: str,
             risk_free_rate: float, combined: pd.DataFrame | None = None,
             out_path: Path | None = None,
             include: list[str] | None = None,
             exclude: list[str] | None = None) -> Path:
    """
    Skorlu + metrik DataFrame'lerden konsolide premium PDF üretir; yolu döndürür.
    `combined` verilirse örnek portföy riski gerçek kovaryanstan hesaplanır (#4).
    """
    paths = config.paths_for(fund_type)
    out_path = Path(out_path) if out_path else paths.report_pdf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chart_dir = paths.report_pdf.parent / "_charts_tmp"
    chart_dir.mkdir(parents=True, exist_ok=True)

    df = scored.copy()
    extra = [c for c in ["Fon_Toplam_Deger_Milyon_TL", "Fon_Yasi_Yil", "Fon_Kurulus_Tarihi",
                         "VaR_95", "CVaR_95", "Reel_Getiri_1Y", "Veri_Kalitesi"]
             if c in metrics.columns and c not in df.columns]
    if extra:
        df = df.merge(metrics[["Fon Kodu"] + extra], on="Fon Kodu", how="left")

    n_funds = len(df)
    df["_tema"] = df["Fon Adi"].map(fund_theme)
    # Öneriler yalnızca UYGUN fonlardan (rf/AUM/yaş kriterlerini geçen); sıralama
    # ise tüm evren üzerinden yapıldı (bkz. metrics.compute_metrics). Uygun yoksa
    # tüm evrene düşülür.
    elig = df[df["Uygun"]].copy() if "Uygun" in df.columns else df.copy()
    if elig.empty:
        elig = df.copy()
    n_elig = int(df["Uygun"].sum()) if "Uygun" in df.columns else n_funds
    styles = _styles()
    today = datetime.now().strftime("%d.%m.%Y")
    story = []

    # 1. Kapak — tüm içerik tek sayfada kalsın diye KeepTogether ile sarılır.
    cover_items = [
        Spacer(1, 48 * mm), Paragraph("TEFAS", styles["CoverTitle"]),
        Paragraph("PREMİUM YATIRIM RAPORU", styles["CoverTitle"]), Spacer(1, 6 * mm),
        Paragraph(f"{paths.fund_name} Fonları &nbsp;|&nbsp; Kantitatif Analiz, Risk Profilleme & Portföy Önerileri", styles["CoverSub"]),
        Spacer(1, 12 * mm),
        Paragraph(f"Rapor Tarihi: {today}<br/>Analiz Edilen Fon Sayısı: {n_funds}<br/>"
                  f"Risksiz Faiz Oranı (Benchmark): %{risk_free_rate:.1f}<br/>"
                  f"Enflasyon (TÜFE): %{config.macro().inflation_rate:.0f} &nbsp;|&nbsp; Politika Faizi: %{config.macro().policy_rate:.0f}", styles["CoverInfo"]),
        Spacer(1, 8 * mm),
    ]
    if include or exclude:
        parts = []
        if include:
            parts.append(f"DAHİL: {', '.join(include)}")
        if exclude:
            parts.append(f"HARİÇ: {', '.join(exclude)}")
        filter_box = Table(
            [[Paragraph("  |  ".join(parts), styles["CoverFilter"])]],
            colWidths=[150 * mm],
        )
        filter_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        cover_items += [filter_box, Spacer(1, 8 * mm)]
    else:
        cover_items.append(Spacer(1, 14 * mm))
    cover_items.append(
        Paragraph("Bu rapor kantitatif modellere dayanır ve yatırım tavsiyesi değildir.", styles["Disclaimer"]))
    story += [KeepTogether(cover_items), PageBreak()]

    # 2. Gösterge paneli (dashboard)
    avg = lambda c: df[c].mean() if c in df.columns else np.nan
    med = lambda c: df[c].median() if c in df.columns else np.nan
    top_overall = elig.nlargest(5, "Overall_Score")
    top10_codes = elig.nlargest(10, "Overall_Score")["Fon Kodu"].tolist()
    ret_all = pd.to_numeric(df["Yillik_Getiri"], errors="coerce")
    real_all = pd.to_numeric(df.get("Reel_Getiri_1Y"), errors="coerce") if "Reel_Getiri_1Y" in df.columns else None
    pf_ = lambda m: f"{m * 100:.0f}%"
    cards = [
        (f"{n_funds:,}", "Analiz edilen fon"),
        (f"{n_elig:,}", "Uygun (rf/AUM/yaş)"),
        (pct(avg("Yillik_Getiri")), "Ort. yıllık getiri"),
        (pct(avg("Yillik_Volatilite")), "Ort. volatilite"),
        (fmt(avg("Sharpe_Orani"), 2), "Ort. Sharpe"),
        (pct(med("Max_Drawdown")), "Medyan Max DD"),
        (pf_((ret_all > config.macro().inflation_rate).mean()), "Enflasyonu geçen"),
        (pf_((real_all > 0).mean()) if real_all is not None else "—", "Pozitif reel getiri"),
    ]
    story += [Paragraph("GÖSTERGE PANELİ", styles["Section"]),
              Paragraph("Analiz evreninin özet göstergeleri ve dağılımları. Yeşil vurgular composite skora göre "
                        "öne çıkan (uygun) fonların evren içindeki konumunu gösterir.", styles["BodySm"]),
              _kpi_cards(cards, styles, ncols=4), Spacer(1, 4 * mm)]
    dist = _chart_distribution(df, top10_codes, risk_free_rate, chart_dir / "dist.png")
    if dist:
        story += [Image(dist, width=232 * mm, height=74 * mm), Spacer(1, 3 * mm)]
    bench_bar = _chart_benchmark_bars(df, risk_free_rate, chart_dir / "bench_bar.png")
    if bench_bar:
        story.append(Image(bench_bar, width=232 * mm, height=45 * mm))
    story.append(PageBreak())

    # 3. Yönetici özeti
    kpi_rows = [["Analiz edilen fon", str(n_funds), "Ort. yıllık getiri", pct(avg("Yillik_Getiri"))],
                ["Ort. volatilite", pct(avg("Yillik_Volatilite")), "Ort. Sharpe", fmt(avg("Sharpe_Orani"), 2)],
                ["Ort. Max Drawdown", pct(avg("Max_Drawdown")), "Ort. composite skor", fmt(avg("Overall_Score"), 1)]]
    kpi_tbl = Table([[Paragraph(f"<b>{a}</b>", styles["Cell"]), Paragraph(b, styles["Cell"]),
                      Paragraph(f"<b>{c}</b>", styles["Cell"]), Paragraph(d, styles["Cell"])] for a, b, c, d in kpi_rows],
                    colWidths=[55 * mm, 40 * mm, 55 * mm, 40 * mm])
    kpi_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                 ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [Paragraph("YÖNETİCİ ÖZETİ", styles["Section"]), kpi_tbl, Spacer(1, 4 * mm),
              Paragraph(f"<b>Öne çıkanlar:</b> Composite skora göre en iyi 5 fon: <b>{', '.join(top_overall['Fon Kodu'].tolist())}</b>. "
                        f"Bu fonlar; risk-ayarlı getiri (Sharpe/Sortino), drawdown kontrolü, getiri ve likidite eksenlerinin "
                        f"yüzdelik-sıra bileşimiyle seçilmiştir. Veri kalitesi şüpheli (> %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} "
                        f"tek-günlük sıçrama) fonlar analiz dışında bırakılmıştır.", styles["Body"]), Spacer(1, 3 * mm)]

    # ── Benchmark karşılaştırması (#2): UYGUN fonlar (rf'yi geçenler) üzerinden;
    #    asıl soru enflasyon/politika faizi ve reel getiri.
    m_infl = int((elig["Yillik_Getiri"] > config.macro().inflation_rate).sum())
    m_pol = int((elig["Yillik_Getiri"] > config.macro().policy_rate).sum())
    has_real = "Reel_Getiri_1Y" in elig.columns
    m_real_pos = int((elig["Reel_Getiri_1Y"] > 0).sum()) if has_real else 0
    avg_real = elig["Reel_Getiri_1Y"].mean() if has_real else np.nan
    p = lambda k: f"{k} / {n_elig} (%{k / n_elig * 100:.0f})" if n_elig else "—"
    bench_rows = [
        [f"Enflasyonu (%{config.macro().inflation_rate:.0f}) geçen", p(m_infl),
         f"Politika faizini (%{config.macro().policy_rate:.0f}) geçen", p(m_pol)],
        ["Pozitif reel getiri", p(m_real_pos),
         "Ortalama reel getiri", pct(avg_real)],
    ]
    bench_tbl = Table([[Paragraph(f"<b>{a}</b>", styles["Cell"]), Paragraph(b, styles["Cell"]),
                        Paragraph(f"<b>{c}</b>", styles["Cell"]), Paragraph(d, styles["Cell"])]
                       for a, b, c, d in bench_rows],
                      colWidths=[55 * mm, 40 * mm, 55 * mm, 40 * mm])
    bench_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHTER), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                   ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [Paragraph(f"Benchmark Karşılaştırması (rf'yi geçen {n_elig} uygun fon üzerinden):", styles["SubSec"]),
              bench_tbl, Spacer(1, 2 * mm)]

    # ── Veri kapsamı uyarısı (#1)
    n_thin = int((df["Veri_Noktasi_Sayisi"] < config.TRADING_DAYS_PER_YEAR).sum())
    med_days = int(df["Veri_Noktasi_Sayisi"].median()) if len(df) else 0
    story += [Paragraph(
        f"<b>Veri kapsamı:</b> medyan gözlem {med_days} iş günü. Analiz edilen fonların "
        f"<b>{n_thin}</b> tanesinin 1 yıldan ({config.TRADING_DAYS_PER_YEAR} iş günü) kısa fiyat geçmişi var; "
        f"bu fonlarda yıllık getiri <b>daha kısa bir pencereden yıllıklandırıldığı</b> için (ve Sharpe) "
        f"gürültülüdür — tablolarda <b>*</b> ile işaretlenir.",
        styles["BodySm"]), Spacer(1, 2 * mm)]

    img = _chart_top_returns(elig, chart_dir / "top_returns.png")
    if img:
        story.append(Image(img, width=200 * mm, height=87 * mm))
    story.append(PageBreak())

    # 4. En iyi fonlar
    headers = ["Kod", "Fon Adı", "Skor", "Yıl. Get.", "Volat.", "Sharpe", "Sortino", "Max DD", "Gerekçe"]
    cw = [13 * mm, 52 * mm, 13 * mm, 16 * mm, 16 * mm, 15 * mm, 15 * mm, 15 * mm, 62 * mm]
    rows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 42), styles["Cell"]),
             Paragraph(fmt(r.get("Overall_Score"), 1), styles["Cell"]), Paragraph(pct(r.get("Yillik_Getiri")), styles["Cell"]),
             Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]), Paragraph(fmt(r.get("Sharpe_Orani"), 2), styles["Cell"]),
             Paragraph(fmt(r.get("Sortino_Orani"), 2), styles["Cell"]), Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"]),
             Paragraph(build_rationale(r), styles["Rationale"])] for _, r in elig.nlargest(12, "Overall_Score").iterrows()]
    story += [Paragraph("EN İYİ FONLAR — GENEL SIRALAMA", styles["Section"]),
              Paragraph("Composite skora göre ilk 12 <b>uygun</b> fon (rf/AUM/yaş kriterlerini geçen) ve her biri için kısa yatırım gerekçesi.", styles["BodySm"]),
              _make_table(headers, rows, cw, styles, align_right_from=2),
              Spacer(1, 2 * mm),
              Paragraph("* 1 yıldan kısa fiyat geçmişi — yıllık getiri daha kısa pencereden yıllıklandırılır, gürültülüdür.", styles["Disclaimer"])]

    growth_chart = _chart_growth_history(combined, top_overall["Fon Kodu"].tolist(), chart_dir / "growth.png")
    if growth_chart:
        story += [Spacer(1, 4 * mm),
                  Image(growth_chart, width=236 * mm, height=110 * mm)]
    story.append(PageBreak())

    # 5. Fon künyeleri (tear-sheet)
    card_rows_src = elig.nlargest(6, "Overall_Score")
    cards_out = []
    for _, r in card_rows_src.iterrows():
        spark = _chart_sparkline(combined, r["Fon Kodu"], chart_dir / f"spark_{r['Fon Kodu']}.png")
        cards_out.append(_fund_card(r, spark, styles, risk_free_rate))
    if cards_out:
        story.append(Paragraph("FON KÜNYELERİ — İLK 6 ÖNERİ", styles["Section"]))
        story.append(Paragraph("Her kart: temel metrikler, tail-risk (VaR/CVaR) ve kuruluştan-bugüne büyüme (üst) ile "
                               "sualtı/drawdown (alt) mini grafiği.", styles["BodySm"]))
        story.append(Spacer(1, 3 * mm))
        for i in range(0, len(cards_out), 3):
            chunk = cards_out[i:i + 3]
            row_tbl = Table([chunk], colWidths=[86 * mm] * len(chunk))
            row_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            story.append(row_tbl)
        story.append(PageBreak())

    # 6. Risk profilleri
    story.append(Paragraph("RİSK PROFİLİNE GÖRE ÖNERİLER", styles["Section"]))
    profile_defs = [
        ("Conservative", "MUHAFAZAKÂR", "Sermaye koruması önceliklidir: düşük volatilite, düşük drawdown, yüksek istikrar ve mevduatı geçen getiri. Genellikle para piyasası ve kısa vadeli borçlanma fonları öne çıkar."),
        ("Balanced", "DENGELİ", "En iyi risk-ayarlı getiri (Sortino/Calmar) orta volatilite bandında. Aşağı yönlü riske duyarlıdır."),
        ("Aggressive", "AGRESİF", "Getiri ve momentum odaklı, daha yüksek volatilite toleransı; yine de pozitif Calmar şartıyla risk-bilinçli."),
    ]
    prof_headers = ["Kod", "Fon Adı", "Tema", "Skor", "Yıl. Get.", "Volat.", "Sharpe", "Max DD"]
    prof_cw = [13 * mm, 60 * mm, 34 * mm, 14 * mm, 17 * mm, 17 * mm, 16 * mm, 16 * mm]
    for key, label, desc in profile_defs:
        col = f"{key}_Score"
        if col not in df.columns:
            continue
        block = [Paragraph(f"{label} Profili", styles["SubSec"]), Paragraph(desc, styles["BodySm"])]
        prows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 50), styles["Cell"]),
                  Paragraph(fund_theme(r["Fon Adi"]), styles["Cell"]), Paragraph(fmt(r.get(col), 1), styles["Cell"]),
                  Paragraph(pct(r.get("Yillik_Getiri")), styles["Cell"]), Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]),
                  Paragraph(fmt(r.get("Sharpe_Orani"), 2), styles["Cell"]), Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"])]
                 for _, r in elig.nlargest(7, col).iterrows()]
        block += [_make_table(prof_headers, prows, prof_cw, styles, align_right_from=3), Spacer(1, 4 * mm)]
        story.append(KeepTogether(block))
    story.append(PageBreak())

    # 7. Önerilen portföy
    story.append(Paragraph("ÖNERİLEN ÇEŞİTLENDİRİLMİŞ PORTFÖY", styles["Section"]))
    portfolio = _build_portfolio(elig)
    if portfolio:
        exp_ret, vol_lo, vol_hi = _portfolio_expected(portfolio)
        risk = pf.portfolio_risk(combined, portfolio)   # #4: gerçek kovaryanstan
        if risk is not None:
            risk_txt = (
                f"<b>Beklenen yıllık getiri (ağırlıklı):</b> %{exp_ret:.1f}<br/>"
                f"<b>Portföy volatilitesi (kovaryans):</b> %{risk['portfolio_vol']:.1f}<br/>"
                f"<b>Çeşitlendirme yok (ağırlıklı ort.):</b> %{risk['weighted_avg_vol']:.1f}  "
                f"→ <b>kazanç</b> %{risk['diversification_gain']:.1f}<br/>"
                f"<b>Ort. ikili korelasyon:</b> {risk['avg_correlation']:.2f} "
                f"({risk['n_used']} fon)<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        else:
            risk_txt = (
                f"<b>Beklenen yıllık getiri (ağırlıklı):</b> %{exp_ret:.1f}<br/>"
                f"<b>Tahmini portföy volatilitesi:</b> %{vol_lo:.1f} – %{vol_hi:.1f} (çeşitlendirme bandı)<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        story.append(Paragraph("Farklı risk profillerinden ve farklı temalardan seçilen, sermaye koruması ağırlıklı örnek bir portföy. "
                               "Portföy volatilitesi fonların gerçek günlük getiri kovaryansından hesaplanır.", styles["BodySm"]))
        pie = _chart_allocation(portfolio, chart_dir / "allocation.png")
        ph = ["Kod", "Fon Adı", "Profil", "Tema", "Ağırlık", "Yıl. Get.", "Volat."]
        pcw = [13 * mm, 50 * mm, 22 * mm, 30 * mm, 16 * mm, 16 * mm, 16 * mm]
        prows = [[Paragraph(str(p["Fon Kodu"]), styles["CellB"]), Paragraph(short_name(p["Fon Adi"], 40), styles["Cell"]),
                  Paragraph(p["Profil"], styles["Cell"]), Paragraph(p["Tema"], styles["Cell"]),
                  Paragraph(pct(p["Agirlik"], 1), styles["Cell"]), Paragraph(pct(p["Yillik_Getiri"]), styles["Cell"]),
                  Paragraph(pct(p["Yillik_Volatilite"]), styles["Cell"])] for p in portfolio]
        ptable = _make_table(ph, prows, pcw, styles, align_right_from=4)
        right = [ptable, Spacer(1, 3 * mm), Paragraph(risk_txt, styles["Body"])]
        layout = Table([[right, Image(pie, width=92 * mm, height=74 * mm)]], colWidths=[163 * mm, 95 * mm])
        layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(layout)

        # Çeşitlendirme + risk sürücüleri — ayrı sayfa (ısı haritası + risk katkısı)
        corr_codes = [p["Fon Kodu"] for p in portfolio]
        heatmap = _chart_correlation_heatmap(combined, corr_codes, chart_dir / "heatmap.png")
        rc_chart = _chart_risk_contribution(risk, portfolio, chart_dir / "risk_contrib.png") if risk is not None else None
        if heatmap or rc_chart:
            story.append(PageBreak())
            story.append(Paragraph("PORTFÖY ÇEŞİTLENDİRMESİ & RİSK SÜRÜCÜLERİ", styles["Section"]))
            if heatmap:
                story += [Paragraph("Korelasyon ısı haritası: fonların günlük getirilerindeki ortak hareket. Düşük/negatif "
                                    "korelasyon (yeşil-sarı tonlar) daha iyi çeşitlendirme sağlar.", styles["BodySm"]),
                          Image(heatmap, width=104 * mm, height=85 * mm)]
            if rc_chart:
                story += [Spacer(1, 2 * mm),
                          Paragraph("Ağırlık vs. gerçek risk katkısı: yüksek volatiliteli veya güçlü korele bir fon, portföy "
                                    "ağırlığının üzerinde risk taşır (RC_i = w_i·(Σw)_i / (w'·Σ·w)).", styles["BodySm"]),
                          Image(rc_chart, width=236 * mm, height=54 * mm)]

        # Portföyün kümülatif değeri + sualtı (drawdown) eğrisi — ayrı sayfa
        uw_chart = _chart_portfolio_underwater(combined, portfolio, chart_dir / "port_uw.png")
        if uw_chart:
            story += [PageBreak(),
                      Paragraph("PORTFÖY PERFORMANSI & SUALTI (DRAWDOWN)", styles["Section"]),
                      Paragraph("Örnek portföyün ağırlıklı günlük getirilerinden türetilen kümülatif değeri (üst) ve zirveye "
                                "göre kayıp/sualtı eğrisi (alt). Sualtı eğrisi geçmişte yaşanan en derin düşüşleri ve "
                                "toparlanma sürelerini gösterir.", styles["BodySm"]),
                      Image(uw_chart, width=250 * mm, height=104 * mm)]
    story.append(PageBreak())

    # 8. Risk-getiri haritası + tail-risk + kategori
    story += [Paragraph("RİSK – GETİRİ HARİTASI", styles["Section"]),
              Paragraph("Tüm fonların risk (volatilite) – getiri konumlanması. Composite skora göre en iyi 10 <b>uygun</b> fon "
                        "yeşil ile işaretlenmiştir. Eksenler 1.–99. yüzdelik aralığına kırpılmıştır.", styles["BodySm"])]
    scatter = _chart_risk_return(df, top10_codes, chart_dir / "risk_return.png")
    if scatter:
        story.append(Image(scatter, width=236 * mm, height=110 * mm))
    story.append(PageBreak())

    # Tail-risk tablosu (B4/A5) — VaR/CVaR artık raporda görünür
    tr_headers = ["Kod", "Fon Adı", "Yıl. Get.", "Volat.", "VaR %95", "VaR %99", "CVaR %95", "En Kötü Gün", "Max DD"]
    tr_cw = [13 * mm, 55 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm, 18 * mm]
    tr_rows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 44), styles["Cell"]),
                Paragraph(pct(r.get("Yillik_Getiri")), styles["Cell"]), Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]),
                Paragraph(pct(r.get("VaR_95")), styles["Cell"]), Paragraph(pct(r.get("VaR_99")), styles["Cell"]),
                Paragraph(pct(r.get("CVaR_95")), styles["Cell"]), Paragraph(pct(r.get("En_Kotu_Gun")), styles["Cell"]),
                Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"])]
               for _, r in elig.nlargest(10, "Overall_Score").iterrows()]
    story += [Paragraph("TAIL-RISK (KUYRUK RİSKİ) — İLK 10 ÖNERİ", styles["Section"]),
              Paragraph("Günlük getirilerden hesaplanan Value-at-Risk (VaR) ve Koşullu VaR (CVaR): kötü bir günde beklenen "
                        "kayıp büyüklüğü. VaR %95 ≈ en kötü %5'lik günlerin eşiği; CVaR o eşiğin ötesindeki ortalama kayıptır.",
                        styles["BodySm"]),
              _make_table(tr_headers, tr_rows, tr_cw, styles, align_right_from=2), Spacer(1, 5 * mm)]
    cat_chart = _chart_category_mix(df, chart_dir / "category.png")
    if cat_chart:
        story.append(KeepTogether([
            Paragraph("Kategori / Tema Dağılımı", styles["SubSec"]),
            Paragraph("Analiz evrenindeki fonların tema kırılımı ve tema başına ortalama yıllık getiri.", styles["BodySm"]),
            Image(cat_chart, width=210 * mm, height=66 * mm)]))
    story.append(PageBreak())

    # 9. Metodoloji
    story.append(Paragraph("METODOLOJİ & UYARILAR", styles["Section"]))
    method = [
        ("Ortak Değerlendirme Penceresi", f"Volatilite, Sharpe, Sortino, Calmar, drawdown ve VaR gibi risk metrikleri tüm fonlarda "
         f"<b>ortak gerilemeli ~1 işlem yılı</b> (son {config.SCORING_LOOKBACK_DAYS} gözlem) penceresinde hesaplanır; böylece farklı "
         "geçmiş uzunluğundaki fonlar aynı dönem üzerinden kıyaslanır. 1 yıldan uzun geçmişli fonlar son pencereye kırpılır; daha "
         "kısa geçmişliler tüm geçmişini kullanır ve <b>*</b> ile işaretlenir. Kuruluştan-bugüne değerler ayrıca künye kartlarında referans olarak verilir."),
        ("Composite Skor", "Sharpe (%25), Sortino (%15), düşük drawdown (%20), yıllık getiri (%25), tutarlılık (%7,5) ve likidite/AUM (%7,5) "
         "eksenlerinin yüzdelik-sıra ağırlıklı bileşimi. Sharpe ve Sortino yüksek korelasyonlu olduğundan toplam ağırlıkları sınırlandırılmıştır. "
         "Tutarlılık skoru pozitif gün/ay oranı ve aylık getiri dağılımına dayanır; drawdown ve Sortino'yu tekrar kullanmaz (çifte sayım yok). "
         "Yüzdelik-sıra skorları uç değerlere karşı dayanıklıdır ve <b>tüm evren</b> üzerinden hesaplanır."),
        ("Sıralama vs. Seçim", "Skorlar tüm (veri-kalitesi geçerli) evren üzerinden hesaplanır; risksiz faiz / AUM / yaş kriterleri "
         "sıralamayı bozmadan bir <b>uygunluk</b> filtresi olarak uygulanır. Öneri tabloları yalnızca uygun fonları listeler; "
         "risk-getiri haritası bağlam için tüm evreni gösterir."),
        ("Risk-Ayarlı Metrikler", "Sharpe = (Getiri − Rf) / Volatilite; Sortino aşağı yönlü sapmayı; Calmar maksimum drawdown'u esas alır. "
         "Volatilite ve Sortino winsorize edilmiş günlük getirilerle hesaplanır. VaR/CVaR tail-risk tablosunda raporlanır."),
        ("Portföy Riski", "Örnek portföyün volatilitesi fonların gerçek günlük getiri kovaryansından σ = √(w'·Σ·w) ile hesaplanır. "
         "Risk katkısı RC_i = w_i·(Σw)_i / (w'·Σ·w) her fonun riske gerçek payını, sualtı eğrisi ise tarihsel drawdown'u gösterir."),
        ("Veri Kalitesi", f"Tek günde > %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} fiyat hareketi yapan fonlar şüpheli kabul edilip analizden çıkarılır."),
        ("Reel Getiri & Vergi", f"Reel getiri Fisher denklemiyle enflasyondan (%{config.macro().inflation_rate:.0f} TÜFE) arındırılır. "
         "<b>Net getiri yalnızca yönetim ücreti düşülerek</b> verilir; stopaj/işlem vergileri tutuş süresi ve fon tipine bağlı olduğundan "
         "(bu veri setinde yok) modellenmez."),
        ("Survivorship Bias", "Analiz yalnızca platformda hâlen aktif olan fonları kapsar. Kapanmış, birleşmiş veya tasfiye edilmiş "
         "fonlar veri setinde bulunmadığından geçmiş performans istatistikleri iyimser yönde sapabilir (survivorship bias)."),
    ]
    for title, body in method:
        story += [Paragraph(title, styles["SubSec"]), Paragraph(body, styles["Body"])]
    story += [Spacer(1, 6 * mm),
              Paragraph("UYARI: Bu rapor yalnızca geçmiş TEFAS verisine uygulanan kantitatif modellere dayanır; yatırım tavsiyesi değildir. "
                        "Geçmiş performans gelecek getiriyi garanti etmez. İşlem maliyetleri ve vergi etkileri tam modellenmemiştir.", styles["Disclaimer"])]

    doc = SimpleDocTemplate(str(out_path), pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=12 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            title=f"TEFAS Premium Rapor - {paths.fund_name}", author="TEFAS Analiz Sistemi v2")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT, 7.5); canvas.setFillColor(GREY)
        canvas.drawString(14 * mm, 6 * mm, f"TEFAS Premium Rapor — {paths.fund_name}  ·  {today}")
        canvas.drawRightString(landscape(A4)[0] - 14 * mm, 6 * mm, f"Sayfa {doc_.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(14 * mm, 9 * mm, landscape(A4)[0] - 14 * mm, 9 * mm)
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    try:
        for p in chart_dir.glob("*.png"):
            p.unlink()
        chart_dir.rmdir()
    except OSError:
        pass

    print(f"[OK] Konsolide premium rapor: {out_path}")
    return out_path


# ═════════════════════════════════════════════════════════════════════════════
#  KARŞILAŞTIRMA MODU  —  belirli fonları yan yana kıyaslayan rapor
# ═════════════════════════════════════════════════════════════════════════════

def _fund_color(codes, code):
    return FUND_PALETTE[codes.index(code) % len(FUND_PALETTE)] if code in codes else MPL_GREY


def _cmp_pivot(combined, codes):
    pivot = combined.pivot_table(index="Tarih", columns="Fon Kodu", values="Fiyat",
                                 aggfunc="first").sort_index()
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return None, []
    pivot.index = pd.to_datetime(pivot.index)
    return pivot[avail], avail


def _chart_cmp_growth(combined, codes, path):
    """Karşılaştırılan fonların ortak dönemde normalize (100 taban) büyümesi."""
    pivot, avail = _cmp_pivot(combined, codes)
    if pivot is None:
        return None
    df = pivot.dropna(how="any")
    if len(df) < 10:
        return None
    norm = df / df.iloc[0] * 100.0
    fig, ax = plt.subplots(figsize=(9.6, 3.7))
    for c in avail:
        ax.plot(norm.index, norm[c], label=c, linewidth=1.7, color=_fund_color(codes, c))
    ax.axhline(100, color=MPL_GREY, linewidth=0.6, linestyle=":")
    ax.set_ylabel("Değer (Başlangıç = 100)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Kümülatif Büyüme (ortak dönem)", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(fontsize=8, loc="upper left", framealpha=0.9, ncol=min(len(avail), 5))
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    return _chart(fig, path)


def _chart_cmp_periods(met, path):
    """Dönemsel getiri (1A/3A/6A/1Y) — fon başına gruplanmış bar."""
    periods = [("1A", "Getiri_1A"), ("3A", "Getiri_3A"), ("6A", "Getiri_6A"), ("1Y", "Getiri_1Y")]
    codes = met["Fon Kodu"].tolist()
    n = len(codes)
    x = np.arange(len(periods))
    width = 0.8 / max(n, 1)
    fig, ax = plt.subplots(figsize=(9.6, 3.4))
    for i, (_, r) in enumerate(met.iterrows()):
        vals = [r.get(col) if pd.notna(r.get(col)) else 0.0 for _, col in periods]
        ax.bar(x + i * width - 0.4 + width / 2, vals, width, label=r["Fon Kodu"],
               color=FUND_PALETTE[i % len(FUND_PALETTE)], alpha=0.9)
    ax.set_xticks(x); ax.set_xticklabels([p for p, _ in periods])
    ax.axhline(0, color=MPL_GREY, linewidth=0.6)
    ax.set_ylabel("Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Dönemsel Getiriler", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.2, linestyle="--")
    ax.legend(fontsize=7.5, ncol=min(n, 6), framealpha=0.9)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _chart_cmp_scatter(met, path):
    """Karşılaştırılan fonların risk (vol) – getiri konumu, etiketli."""
    d = met.dropna(subset=["Yillik_Volatilite", "Yillik_Getiri"])
    if len(d) < 1:
        return None
    fig, ax = plt.subplots(figsize=(9.0, 3.1))
    for i, (_, r) in enumerate(met.iterrows()):
        if pd.isna(r["Yillik_Volatilite"]) or pd.isna(r["Yillik_Getiri"]):
            continue
        c = FUND_PALETTE[i % len(FUND_PALETTE)]
        ax.scatter(r["Yillik_Volatilite"], r["Yillik_Getiri"], s=110, color=c,
                   edgecolors="white", linewidths=1.0, zorder=3)
        ax.annotate(str(r["Fon Kodu"]), (r["Yillik_Volatilite"], r["Yillik_Getiri"]),
                    xytext=(6, 5), textcoords="offset points", fontsize=8.5,
                    fontweight="bold", color=MPL_NAVY)
    ax.set_xlabel("Yıllık Volatilite (%)", fontsize=9, color=MPL_NAVY)
    ax.set_ylabel("Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Risk – Getiri Konumu", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.margins(0.18)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def _chart_cmp_drawdown(combined, codes, path):
    """Her fonun sualtı (drawdown) eğrisi tek eksende — dayanıklılık kıyası."""
    pivot, avail = _cmp_pivot(combined, codes)
    if pivot is None:
        return None
    fig, ax = plt.subplots(figsize=(9.6, 3.4))
    plotted = False
    for c in avail:
        s = pivot[c].dropna()
        if len(s) < 10:
            continue
        p = s.to_numpy()
        peak = np.maximum.accumulate(p)
        dd = (peak - p) / peak * 100.0
        ax.plot(s.index, dd, label=c, linewidth=1.3, color=_fund_color(codes, c))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.invert_yaxis()
    ax.set_ylabel("Drawdown (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Sualtı (Drawdown) Karşılaştırması — sıfıra yakın daha iyi", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(fontsize=8, loc="lower left", framealpha=0.9, ncol=min(len(avail), 5))
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


_RADAR_AXES = [("Yıllık Getiri", "Yillik_Getiri", "high"), ("Sharpe", "Sharpe_Orani", "high"),
               ("Sortino", "Sortino_Orani", "high"), ("Düşük Vol.", "Yillik_Volatilite", "low"),
               ("Düşük DD", "Max_Drawdown", "low"), ("Poz. Gün", "Pozitif_Gun_Orani", "high")]


def _chart_cmp_radar(met, path):
    """Çok-boyutlu göreli karşılaştırma (fonlar arası min-maks normalize spider)."""
    labels = [a[0] for a in _RADAR_AXES]
    norm = []
    for _, col, direction in _RADAR_AXES:
        vals = pd.to_numeric(met[col], errors="coerce").to_numpy(dtype="float64")
        vmin, vmax = np.nanmin(vals), np.nanmax(vals)
        if not np.isfinite(vmin) or vmax == vmin:
            scaled = np.full(len(vals), 0.5)
        else:
            scaled = (vals - vmin) / (vmax - vmin)
            if direction == "low":
                scaled = 1.0 - scaled
        norm.append(np.nan_to_num(scaled, nan=0.0))
    norm = np.array(norm)
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]
    fig, ax = plt.subplots(figsize=(5.4, 4.4), subplot_kw=dict(polar=True))
    for i, (_, r) in enumerate(met.iterrows()):
        vals = norm[:, i].tolist()
        vals += vals[:1]
        c = FUND_PALETTE[i % len(FUND_PALETTE)]
        ax.plot(angles, vals, color=c, linewidth=1.7, label=str(r["Fon Kodu"]))
        ax.fill(angles, vals, color=c, alpha=0.07)
    ax.set_thetagrids(np.degrees(angles[:-1]), labels, fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75])
    ax.set_yticklabels([])
    ax.set_title("Çok-Boyutlu Karşılaştırma (fonlar arası göreli)", fontsize=10.5,
                 color=MPL_NAVY, fontweight="bold", pad=18)
    ax.legend(loc="upper right", bbox_to_anchor=(1.28, 1.12), fontsize=8, framealpha=0.9)
    fig.tight_layout()
    return _chart(fig, path)


# metrik satırı: (etiket, (sütun, yön) | None, biçimlendirici)
_CMP_ROWS = [
    ("Tema", None, lambda r: fund_theme(r.get("Fon Adi"))),
    ("Yıllık Getiri", ("Yillik_Getiri", "high"), lambda r: pct(r.get("Yillik_Getiri"))),
    ("Kuruluş CAGR", ("Yillik_Getiri_Kurulus", "high"), lambda r: pct(r.get("Yillik_Getiri_Kurulus"))),
    ("Volatilite", ("Yillik_Volatilite", "low"), lambda r: pct(r.get("Yillik_Volatilite"))),
    ("Sharpe", ("Sharpe_Orani", "high"), lambda r: fmt(r.get("Sharpe_Orani"), 2)),
    ("Sortino", ("Sortino_Orani", "high"), lambda r: fmt(r.get("Sortino_Orani"), 2)),
    ("Calmar", ("Calmar_Orani", "high"), lambda r: fmt(r.get("Calmar_Orani"), 2)),
    ("Max Drawdown", ("Max_Drawdown", "low"), lambda r: pct(r.get("Max_Drawdown"))),
    ("VaR %95 (gün)", ("VaR_95", "high"), lambda r: pct(r.get("VaR_95"))),
    ("CVaR %95 (gün)", ("CVaR_95", "high"), lambda r: pct(r.get("CVaR_95"))),
    ("Pozitif Gün %", ("Pozitif_Gun_Orani", "high"), lambda r: pct(r.get("Pozitif_Gun_Orani"))),
    ("Pozitif Ay %", ("Pozitif_Ay_Orani", "high"), lambda r: pct(r.get("Pozitif_Ay_Orani"))),
    ("Reel Getiri", ("Reel_Getiri_1Y", "high"), lambda r: pct(r.get("Reel_Getiri_1Y"))),
    ("AUM (mn TL)", ("Fon_Toplam_Deger_Milyon_TL", "high"), lambda r: fmt(r.get("Fon_Toplam_Deger_Milyon_TL"), 0)),
    ("Fon Yaşı (yıl)", None, lambda r: fmt(r.get("Fon_Yasi_Yil"), 1)),
    ("Veri (gün)", None, lambda r: fmt(r.get("Veri_Noktasi_Sayisi"), 0)),
]


def _best_index(met, col, direction):
    vals = pd.to_numeric(met[col], errors="coerce")
    if not vals.notna().any():
        return None
    return int(vals.idxmax() if direction == "high" else vals.idxmin())


def generate_comparison(met: pd.DataFrame, combined: pd.DataFrame, fund_type: str,
                        risk_free_rate: float, codes: list[str],
                        out_path: Path | None = None) -> Path:
    """Belirli fonları yan yana kıyaslayan PDF üretir; yolu döndürür."""
    paths = config.paths_for(fund_type)
    out_path = Path(out_path) if out_path else paths.comparison_pdf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chart_dir = out_path.parent / "_cmp_charts_tmp"
    chart_dir.mkdir(parents=True, exist_ok=True)

    met = met.reset_index(drop=True)
    codes = met["Fon Kodu"].tolist()
    n = len(met)
    styles = _styles()
    today = datetime.now().strftime("%d.%m.%Y")
    story = []

    def best_code(col, direction):
        idx = _best_index(met, col, direction)
        return str(met.loc[idx, "Fon Kodu"]) if idx is not None else "—"

    # 1) Kapak
    cover = [
        Spacer(1, 42 * mm), Paragraph("TEFAS", styles["CoverTitle"]),
        Paragraph("FON KARŞILAŞTIRMA RAPORU", styles["CoverTitle"]), Spacer(1, 6 * mm),
        Paragraph(f"{paths.fund_name} Fonları &nbsp;|&nbsp; {n} fon yan yana kıyaslanıyor", styles["CoverSub"]),
        Spacer(1, 12 * mm),
        Paragraph(f"Rapor Tarihi: {today}<br/>"
                  f"Karşılaştırılan Fonlar: <b>{', '.join(codes)}</b><br/>"
                  f"Risksiz Faiz (Benchmark): %{risk_free_rate:.1f} &nbsp;|&nbsp; "
                  f"Enflasyon: %{config.macro().inflation_rate:.0f}", styles["CoverInfo"]),
        Spacer(1, 10 * mm),
        Paragraph("Bu rapor kantitatif modellere dayanır ve yatırım tavsiyesi değildir. "
                  "Fonlar 'olduğu gibi' kıyaslanır; aktiflik/uygunluk filtresi uygulanmaz.", styles["Disclaimer"]),
    ]
    story += [KeepTogether(cover), PageBreak()]

    # 2) Özet & öne çıkanlar (verdict + radar)
    story.append(Paragraph("ÖZET & ÖNE ÇIKANLAR", styles["Section"]))
    verdict = [
        ("En yüksek yıllık getiri", best_code("Yillik_Getiri", "high")),
        ("En iyi risk-ayarlı getiri (Sharpe)", best_code("Sharpe_Orani", "high")),
        ("En iyi aşağı-yön koruması (Sortino)", best_code("Sortino_Orani", "high")),
        ("En düşük volatilite", best_code("Yillik_Volatilite", "low")),
        ("En iyi drawdown kontrolü", best_code("Max_Drawdown", "low")),
        ("En yüksek pozitif reel getiri", best_code("Reel_Getiri_1Y", "high")),
        ("En yüksek likidite (AUM)", best_code("Fon_Toplam_Deger_Milyon_TL", "high")),
        ("En tutarlı (pozitif gün oranı)", best_code("Pozitif_Gun_Orani", "high")),
    ]
    vrows = [[Paragraph(f"<b>{k}</b>", styles["Cell"]), Paragraph(v, styles["CellB"])] for k, v in verdict]
    vtbl = Table(vrows, colWidths=[78 * mm, 26 * mm])
    vtbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("TEXTCOLOR", (1, 0), (1, -1), NAVY),
    ]))
    radar = _chart_cmp_radar(met, chart_dir / "radar.png")
    intro = Paragraph("Her satır, kıyaslanan fonlar arasında ilgili ölçütte <b>en iyi</b> olanı gösterir. "
                      "Sağdaki radar, fonların altı boyuttaki göreli konumunu (fonlar arası min-maks normalize) özetler; "
                      "geniş alan çok-yönlü güçlü profil demektir.", styles["BodySm"])
    if radar:
        layout = Table([[[intro, Spacer(1, 3 * mm), vtbl], Image(radar, width=118 * mm, height=96 * mm)]],
                       colWidths=[112 * mm, 122 * mm])
        layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(layout)
    else:
        story += [intro, Spacer(1, 3 * mm), vtbl]
    story.append(PageBreak())

    # 3) Karşılaştırma tablosu (metrikler satır, fonlar sütun; en-iyi vurgulu)
    story.append(Paragraph("KARŞILAŞTIRMA TABLOSU", styles["Section"]))
    story.append(Paragraph("Yeşil hücre, o satırdaki ölçüt için en iyi fonu işaretler. "
                           "<b>*</b>: 1 yıldan kısa fiyat geçmişi (metrikler sınırlı güvenilirlikte).", styles["BodySm"]))
    best_by_row = {ri: (_best_index(met, spec[0], spec[1]) if spec else None)
                   for ri, (_, spec, _) in enumerate(_CMP_ROWS)}
    header = [Paragraph("Metrik", styles["CellH"])] + [Paragraph(_code_label(r), styles["CellH"]) for _, r in met.iterrows()]
    data = [header]
    for ri, (label, spec, fn) in enumerate(_CMP_ROWS):
        row = [Paragraph(label, styles["CellB"])]
        for ci, (_, r) in enumerate(met.iterrows()):
            st = styles["CellB"] if best_by_row.get(ri) == ci else styles["Cell"]
            row.append(Paragraph(fn(r), st))
        data.append(row)
    fund_w = max(24, min(60, (244 - 52) / n))
    tbl = Table(data, colWidths=[52 * mm] + [fund_w * mm] * n, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("LINEBELOW", (0, 0), (-1, 0), 0.5, NAVY),
        ("BACKGROUND", (0, 1), (0, -1), LIGHT),
        ("ROWBACKGROUNDS", (1, 1), (-1, -1), [colors.white, LIGHTER]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for ri, best in best_by_row.items():
        if best is not None:
            ts.append(("BACKGROUND", (best + 1, ri + 1), (best + 1, ri + 1), GOOD))
    tbl.setStyle(TableStyle(ts))
    story += [tbl, PageBreak()]

    # 4) Getiri & büyüme
    story.append(Paragraph("GETİRİ & BÜYÜME", styles["Section"]))
    g = _chart_cmp_growth(combined, codes, chart_dir / "cmp_growth.png")
    if g:
        story += [Image(g, width=236 * mm, height=84 * mm), Spacer(1, 3 * mm)]
    pr = _chart_cmp_periods(met, chart_dir / "cmp_periods.png")
    if pr:
        story.append(Image(pr, width=236 * mm, height=76 * mm))
    story.append(PageBreak())

    # 5) Risk & dayanıklılık
    story.append(Paragraph("RİSK & DAYANIKLILIK", styles["Section"]))
    sc = _chart_cmp_scatter(met, chart_dir / "cmp_scatter.png")
    if sc:
        story += [Image(sc, width=214 * mm, height=74 * mm), Spacer(1, 3 * mm)]
    dd = _chart_cmp_drawdown(combined, codes, chart_dir / "cmp_dd.png")
    if dd:
        story.append(Image(dd, width=236 * mm, height=76 * mm))
    story.append(PageBreak())

    # 6) Korelasyon + notlar
    heat = _chart_correlation_heatmap(combined, codes, chart_dir / "cmp_heat.png")
    if heat:
        story += [Paragraph("BİRLİKTE HAREKET (KORELASYON)", styles["Section"]),
                  Paragraph("İki fonun günlük getirileri ne kadar birlikte hareket ediyor? Düşük/negatif korelasyon "
                            "(yeşil-sarı) bir arada tutulduklarında daha iyi çeşitlendirme sağlar.", styles["BodySm"]),
                  Image(heat, width=120 * mm, height=98 * mm), Spacer(1, 4 * mm)]
    story += [
        Paragraph("Yöntem & Uyarılar", styles["SubSec"]),
        Paragraph(f"Risk metrikleri (volatilite, Sharpe, Sortino, Calmar, drawdown, VaR) tüm fonlarda ortak gerilemeli "
                  f"~1 işlem yılı (son {config.SCORING_LOOKBACK_DAYS} gözlem) penceresinde hesaplanır; kuruluş CAGR referanstır. "
                  "Sharpe = (Getiri − Rf)/Volatilite; Sortino aşağı-yön sapmasını, Calmar drawdown'u esas alır. "
                  "VaR/CVaR %95 günlük kayıp eşiğidir (sıfıra yakın daha iyi). Fonlar 'olduğu gibi' kıyaslanır; "
                  "aktiflik/uygunluk filtresi uygulanmaz.", styles["Body"]),
        Paragraph("UYARI: Bu rapor geçmiş TEFAS verisine dayanır; yatırım tavsiyesi değildir. Geçmiş performans geleceği "
                  "garanti etmez. İşlem maliyetleri ve vergi etkileri modellenmemiştir.", styles["Disclaimer"]),
    ]

    doc = SimpleDocTemplate(str(out_path), pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=12 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            title=f"TEFAS Karşılaştırma - {paths.fund_name}", author="TEFAS Analiz Sistemi v2")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT, 7.5); canvas.setFillColor(GREY)
        canvas.drawString(14 * mm, 6 * mm, f"TEFAS Fon Karşılaştırma — {paths.fund_name}  ·  {today}")
        canvas.drawRightString(landscape(A4)[0] - 14 * mm, 6 * mm, f"Sayfa {doc_.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(14 * mm, 9 * mm, landscape(A4)[0] - 14 * mm, 9 * mm)
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    try:
        for p in chart_dir.glob("*.png"):
            p.unlink()
        chart_dir.rmdir()
    except OSError:
        pass

    print(f"[OK] Karşılaştırma raporu: {out_path}")
    return out_path

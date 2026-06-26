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
    ret = row.get("Getiri_1Y")
    if pd.notna(ret) and ret >= 60:
        bits.append(f"yüksek 1Y getiri (%{fmt(ret,1)})")
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
    d = df.nlargest(n, "Overall_Score").dropna(subset=["Getiri_1Y"]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9.6, 4.2))
    bars = ax.barh(d["Fon Kodu"], d["Getiri_1Y"], color=MPL_BLUE, alpha=0.9)
    ax.bar_label(bars, labels=[f"%{v:.0f}" for v in d["Getiri_1Y"]], fontsize=7.5, padding=3, color=MPL_NAVY)
    ax.set_xlabel("1 Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("En İyi Fonlar — 1 Yıllık Getiri", fontsize=11, color=MPL_NAVY, fontweight="bold")
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
    d = df.dropna(subset=["Yillik_Volatilite", "Getiri_1Y"]).copy()
    if len(d) < 5:
        return None
    x, y = d["Yillik_Volatilite"], d["Getiri_1Y"]
    xlo, xhi = np.percentile(x, 1), np.percentile(x, 99)
    ylo, yhi = np.percentile(y, 1), np.percentile(y, 99)
    xpad, ypad = (xhi - xlo) * 0.05 + 0.5, (yhi - ylo) * 0.05 + 0.5
    fig, ax = plt.subplots(figsize=(9.6, 4.5))
    ax.scatter(x, y, s=14, c=MPL_GREY, alpha=0.55, edgecolors="none", label="Tüm fonlar", zorder=1)
    hl = d[d["Fon Kodu"].isin(highlight_codes)].copy()
    ax.scatter(hl["Yillik_Volatilite"], hl["Getiri_1Y"], s=70, c=MPL_GREEN,
               edgecolors="white", linewidths=0.8, label="Öne çıkan fonlar", zorder=3)
    x0, x1 = max(0, xlo - xpad), xhi + xpad
    y0, y1 = ylo - ypad, yhi + ypad
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    hl = hl[(hl["Yillik_Volatilite"].between(x0, x1)) & (hl["Getiri_1Y"].between(y0, y1))]
    if len(hl) > 0:
        hl = hl.sort_values("Getiri_1Y", ascending=False).reset_index(drop=True)
        n = len(hl)
        label_x = x0 + (x1 - x0) * 0.10
        span_hi, span_lo = y0 + (y1 - y0) * 0.97, y0 + (y1 - y0) * 0.42
        label_ys = np.linspace(span_hi, span_lo, n) if n > 1 else np.array([(span_hi + span_lo) / 2])
        for i, (_, r) in enumerate(hl.iterrows()):
            ax.annotate(str(r["Fon Kodu"]), xy=(r["Yillik_Volatilite"], r["Getiri_1Y"]),
                        xytext=(label_x, label_ys[i]), fontsize=7.5, color=MPL_NAVY, fontweight="bold",
                        va="center", ha="left", zorder=5,
                        bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=MPL_GREEN, lw=0.6, alpha=0.95),
                        arrowprops=dict(arrowstyle="-", color=MPL_GREEN, lw=0.6, alpha=0.65, shrinkA=2, shrinkB=3))
    ax.set_xlabel("Yıllık Volatilite (%)", fontsize=9, color=MPL_NAVY)
    ax.set_ylabel("1 Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("Risk – Getiri Haritası  (eksenler 1.–99. yüzdelik ile kırpıldı)", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.legend(fontsize=8, loc="lower right", framealpha=0.9)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
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
                              "Tema": theme, "Agirlik": weight, "Getiri_1Y": r.get("Getiri_1Y"),
                              "Yillik_Volatilite": r.get("Yillik_Volatilite"), "Sharpe_Orani": r.get("Sharpe_Orani")})
            used_codes.add(code); used_themes.add(theme); picked += 1
    total = sum(p["Agirlik"] for p in portfolio)
    if total > 0:
        for p in portfolio:
            p["Agirlik"] = p["Agirlik"] / total * 100.0
    return portfolio


def _portfolio_expected(portfolio):
    w = np.array([p["Agirlik"] / 100.0 for p in portfolio])
    r = np.array([p["Getiri_1Y"] if pd.notna(p["Getiri_1Y"]) else 0.0 for p in portfolio])
    v = np.array([p["Yillik_Volatilite"] if pd.notna(p["Yillik_Volatilite"]) else 0.0 for p in portfolio])
    return float(np.sum(w * r)), float(np.sqrt(np.sum((w * v) ** 2))), float(np.sum(w * v))


def generate(scored: pd.DataFrame, metrics: pd.DataFrame, fund_type: str,
             risk_free_rate: float, combined: pd.DataFrame | None = None,
             out_path: Path | None = None) -> Path:
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
    styles = _styles()
    today = datetime.now().strftime("%d.%m.%Y")
    story = []

    # 1. Kapak
    story += [Spacer(1, 70 * mm), Paragraph("TEFAS", styles["CoverTitle"]),
              Paragraph("PREMİUM YATIRIM RAPORU", styles["CoverTitle"]), Spacer(1, 6 * mm),
              Paragraph(f"{paths.fund_name} Fonları &nbsp;|&nbsp; Kantitatif Analiz, Risk Profilleme & Portföy Önerileri", styles["CoverSub"]),
              Spacer(1, 14 * mm),
              Paragraph(f"Rapor Tarihi: {today}<br/>Analiz Edilen Fon Sayısı: {n_funds}<br/>"
                        f"Risksiz Faiz Oranı (Benchmark): %{risk_free_rate:.1f}<br/>"
                        f"Enflasyon (TÜFE): %{config.INFLATION_RATE:.0f} &nbsp;|&nbsp; Politika Faizi: %{config.POLICY_RATE:.0f}", styles["CoverInfo"]),
              Spacer(1, 26 * mm),
              Paragraph("Bu rapor kantitatif modellere dayanır ve yatırım tavsiyesi değildir.", styles["Disclaimer"]),
              PageBreak()]

    # 2. Yönetici özeti
    avg = lambda c: df[c].mean() if c in df.columns else np.nan
    top_overall = df.nlargest(5, "Overall_Score")
    kpi_rows = [["Analiz edilen fon", str(n_funds), "Ort. yıllık getiri", pct(avg("Getiri_1Y"))],
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

    # ── Benchmark karşılaştırması (#2): bu fonlar zaten mevduatı geçiyor (rf filtresi);
    #    asıl soru enflasyon/politika faizi ve reel getiri.
    n_infl = int((df["Getiri_1Y"] > config.INFLATION_RATE).sum())
    n_pol = int((df["Getiri_1Y"] > config.POLICY_RATE).sum())
    has_real = "Reel_Getiri_1Y" in df.columns
    n_real_pos = int((df["Reel_Getiri_1Y"] > 0).sum()) if has_real else 0
    avg_real = df["Reel_Getiri_1Y"].mean() if has_real else np.nan
    p = lambda k: f"{k} / {n_funds} (%{k / n_funds * 100:.0f})" if n_funds else "—"
    bench_rows = [
        [f"Enflasyonu (%{config.INFLATION_RATE:.0f}) geçen", p(n_infl),
         f"Politika faizini (%{config.POLICY_RATE:.0f}) geçen", p(n_pol)],
        ["Pozitif reel getiri", p(n_real_pos),
         "Ortalama reel getiri", pct(avg_real)],
    ]
    bench_tbl = Table([[Paragraph(f"<b>{a}</b>", styles["Cell"]), Paragraph(b, styles["Cell"]),
                        Paragraph(f"<b>{c}</b>", styles["Cell"]), Paragraph(d, styles["Cell"])]
                       for a, b, c, d in bench_rows],
                      colWidths=[55 * mm, 40 * mm, 55 * mm, 40 * mm])
    bench_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHTER), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                   ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [Paragraph("Benchmark Karşılaştırması (analiz evreni mevduatı zaten geçiyor):", styles["SubSec"]),
              bench_tbl, Spacer(1, 2 * mm)]

    # ── Veri kapsamı uyarısı (#1)
    n_thin = int((df["Veri_Noktasi_Sayisi"] < config.TRADING_DAYS_PER_YEAR).sum())
    med_days = int(df["Veri_Noktasi_Sayisi"].median()) if len(df) else 0
    story += [Paragraph(
        f"<b>Veri kapsamı:</b> medyan gözlem {med_days} iş günü. Analiz edilen fonların "
        f"<b>{n_thin}</b> tanesinin 1 yıldan ({config.TRADING_DAYS_PER_YEAR} iş günü) kısa fiyat geçmişi var; "
        f"bu fonlarda 1Y getiri ve Sharpe sınırlı güvenilirliktedir ve tablolarda <b>*</b> ile işaretlenir.",
        styles["BodySm"]), Spacer(1, 2 * mm)]

    img = _chart_top_returns(df, chart_dir / "top_returns.png")
    if img:
        story.append(Image(img, width=200 * mm, height=87 * mm))
    story.append(PageBreak())

    # 3. En iyi fonlar
    headers = ["Kod", "Fon Adı", "Skor", "1Y Get.", "Volat.", "Sharpe", "Sortino", "Max DD", "Gerekçe"]
    cw = [13 * mm, 52 * mm, 13 * mm, 16 * mm, 16 * mm, 15 * mm, 15 * mm, 15 * mm, 62 * mm]
    rows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 42), styles["Cell"]),
             Paragraph(fmt(r.get("Overall_Score"), 1), styles["Cell"]), Paragraph(pct(r.get("Getiri_1Y")), styles["Cell"]),
             Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]), Paragraph(fmt(r.get("Sharpe_Orani"), 2), styles["Cell"]),
             Paragraph(fmt(r.get("Sortino_Orani"), 2), styles["Cell"]), Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"]),
             Paragraph(build_rationale(r), styles["Rationale"])] for _, r in df.nlargest(12, "Overall_Score").iterrows()]
    story += [Paragraph("EN İYİ FONLAR — GENEL SIRALAMA", styles["Section"]),
              Paragraph("Composite skora göre ilk 12 fon ve her biri için kısa yatırım gerekçesi.", styles["BodySm"]),
              _make_table(headers, rows, cw, styles, align_right_from=2),
              Spacer(1, 2 * mm),
              Paragraph("* 1 yıldan kısa fiyat geçmişi — 1Y getiri ve Sharpe sınırlı güvenilirliktedir.", styles["Disclaimer"]),
              PageBreak()]

    # 4. Risk profilleri
    story.append(Paragraph("RİSK PROFİLİNE GÖRE ÖNERİLER", styles["Section"]))
    profile_defs = [
        ("Conservative", "MUHAFAZAKÂR", "Sermaye koruması önceliklidir: düşük volatilite, düşük drawdown, yüksek istikrar ve mevduatı geçen getiri. Genellikle para piyasası ve kısa vadeli borçlanma fonları öne çıkar."),
        ("Balanced", "DENGELİ", "En iyi risk-ayarlı getiri (Sortino/Calmar) orta volatilite bandında. Aşağı yönlü riske duyarlıdır."),
        ("Aggressive", "AGRESİF", "Getiri ve momentum odaklı, daha yüksek volatilite toleransı; yine de pozitif Calmar şartıyla risk-bilinçli."),
    ]
    prof_headers = ["Kod", "Fon Adı", "Tema", "Skor", "1Y Get.", "Volat.", "Sharpe", "Max DD"]
    prof_cw = [13 * mm, 60 * mm, 34 * mm, 14 * mm, 17 * mm, 17 * mm, 16 * mm, 16 * mm]
    for key, label, desc in profile_defs:
        col = f"{key}_Score"
        if col not in df.columns:
            continue
        block = [Paragraph(f"{label} Profili", styles["SubSec"]), Paragraph(desc, styles["BodySm"])]
        prows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 50), styles["Cell"]),
                  Paragraph(fund_theme(r["Fon Adi"]), styles["Cell"]), Paragraph(fmt(r.get(col), 1), styles["Cell"]),
                  Paragraph(pct(r.get("Getiri_1Y")), styles["Cell"]), Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]),
                  Paragraph(fmt(r.get("Sharpe_Orani"), 2), styles["Cell"]), Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"])]
                 for _, r in df.nlargest(7, col).iterrows()]
        block += [_make_table(prof_headers, prows, prof_cw, styles, align_right_from=3), Spacer(1, 4 * mm)]
        story.append(KeepTogether(block))
    story.append(PageBreak())

    # 5. Önerilen portföy
    story.append(Paragraph("ÖNERİLEN ÇEŞİTLENDİRİLMİŞ PORTFÖY", styles["Section"]))
    portfolio = _build_portfolio(df)
    if portfolio:
        exp_ret, vol_lo, vol_hi = _portfolio_expected(portfolio)
        risk = pf.portfolio_risk(combined, portfolio)   # #4: gerçek kovaryanstan
        if risk is not None:
            risk_txt = (
                f"<b>Beklenen 1Y getiri (ağırlıklı):</b> %{exp_ret:.1f}<br/>"
                f"<b>Portföy volatilitesi (kovaryans):</b> %{risk['portfolio_vol']:.1f}<br/>"
                f"<b>Çeşitlendirme yok (ağırlıklı ort.):</b> %{risk['weighted_avg_vol']:.1f}  "
                f"→ <b>kazanç</b> %{risk['diversification_gain']:.1f}<br/>"
                f"<b>Ort. ikili korelasyon:</b> {risk['avg_correlation']:.2f} "
                f"({risk['n_used']} fon)<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        else:
            risk_txt = (
                f"<b>Beklenen 1Y getiri (ağırlıklı):</b> %{exp_ret:.1f}<br/>"
                f"<b>Tahmini portföy volatilitesi:</b> %{vol_lo:.1f} – %{vol_hi:.1f} (çeşitlendirme bandı)<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        story.append(Paragraph("Farklı risk profillerinden ve farklı temalardan seçilen, sermaye koruması ağırlıklı örnek bir portföy. "
                               "Portföy volatilitesi fonların gerçek günlük getiri kovaryansından hesaplanır.", styles["BodySm"]))
        pie = _chart_allocation(portfolio, chart_dir / "allocation.png")
        ph = ["Kod", "Fon Adı", "Profil", "Tema", "Ağırlık", "1Y Get.", "Volat."]
        pcw = [13 * mm, 50 * mm, 22 * mm, 30 * mm, 16 * mm, 16 * mm, 16 * mm]
        prows = [[Paragraph(str(p["Fon Kodu"]), styles["CellB"]), Paragraph(short_name(p["Fon Adi"], 40), styles["Cell"]),
                  Paragraph(p["Profil"], styles["Cell"]), Paragraph(p["Tema"], styles["Cell"]),
                  Paragraph(pct(p["Agirlik"], 1), styles["Cell"]), Paragraph(pct(p["Getiri_1Y"]), styles["Cell"]),
                  Paragraph(pct(p["Yillik_Volatilite"]), styles["Cell"])] for p in portfolio]
        ptable = _make_table(ph, prows, pcw, styles, align_right_from=4)
        right = [ptable, Spacer(1, 3 * mm), Paragraph(risk_txt, styles["Body"])]
        layout = Table([[right, Image(pie, width=92 * mm, height=74 * mm)]], colWidths=[163 * mm, 95 * mm])
        layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(layout)
    story.append(PageBreak())

    # 6. Risk-getiri haritası
    story += [Paragraph("RİSK – GETİRİ HARİTASI", styles["Section"]),
              Paragraph("Tüm fonların risk (volatilite) – getiri konumlanması. Composite skora göre en iyi 10 fon yeşil ile "
                        "işaretlenmiştir. Eksenler 1.–99. yüzdelik aralığına kırpılmıştır.", styles["BodySm"])]
    scatter = _chart_risk_return(df, df.nlargest(10, "Overall_Score")["Fon Kodu"].tolist(), chart_dir / "risk_return.png")
    if scatter:
        story.append(Image(scatter, width=236 * mm, height=110 * mm))
    story.append(PageBreak())

    # 7. Metodoloji
    story.append(Paragraph("METODOLOJİ & UYARILAR", styles["Section"]))
    method = [
        ("Composite Skor", "Sharpe (%30), Sortino (%20), düşük drawdown (%20), 1Y getiri (%20), tutarlılık (%5) ve likidite/AUM (%5) "
         "eksenlerinin yüzdelik-sıra ağırlıklı bileşimi. Yüzdelik-sıra skorları uç değerlere karşı dayanıklı kılar."),
        ("Risk-Ayarlı Metrikler", "Sharpe = (Getiri − Rf) / Volatilite; Sortino aşağı yönlü sapmayı; Calmar maksimum drawdown'u esas alır. "
         "Volatilite ve Sortino winsorize edilmiş günlük getirilerle hesaplanır."),
        ("Treynor & Beta", f"Treynor = (Getiri − Rf) / Beta. Beta eşit-ağırlıklı fon evreni benchmark'ına göre hesaplanır; "
         f"|Beta| < {config.MIN_BETA_FOR_TREYNOR} olan fonlarda Treynor raporlanmaz."),
        ("Veri Kalitesi", f"Tek günde > %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} fiyat hareketi yapan fonlar şüpheli kabul edilip sıralamalardan çıkarılır."),
        ("Reel Getiri", f"Fisher denklemiyle enflasyondan (%{config.INFLATION_RATE:.0f} TÜFE) arındırılmış getiri."),
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

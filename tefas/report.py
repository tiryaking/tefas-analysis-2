"""
Konsolide premium PDF rapor — yalnızca YERLEŞİM.

FINDING #1 — v1 raporu CSV'leri diskten tekrar okuyordu. Burada `generate`
skorlu ve metrik DataFrame'leri doğrudan alır (in-process).

High-value refactor: grafik çizimi `charts.py`'ye, portföy kurulum/tahsis
mantığı `allocation.py`'ye taşındı; bu modülde ReportLab yerleşimi kaldı.
Fiyat pivotu `charts.price_pivot` ile BİR KEZ kurulup pivot gerektiren
üreticilere geçirilir. Section başlıkları otomatik PDF outline (yer imi) ve
İÇİNDEKİLER sayfası üretir (bkz. `_OutlineDoc`).
"""
from __future__ import annotations

import zlib
from datetime import datetime
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import allocation, config, portfolio as pf, themes, validation
from .themes import fund_theme  # geriye uyumluluk: report.fund_theme kullanılıyordu
from .charts import (
    FUND_PALETTE,
    price_pivot,
    chart_top_returns as _chart_top_returns,
    chart_allocation as _chart_allocation,
    chart_risk_return as _chart_risk_return,
    chart_growth_history as _chart_growth_history,
    chart_correlation_heatmap as _chart_correlation_heatmap,
    chart_distribution as _chart_distribution,
    chart_benchmark_bars as _chart_benchmark_bars,
    chart_sparkline as _chart_sparkline,
    chart_risk_contribution as _chart_risk_contribution,
    chart_portfolio_underwater as _chart_portfolio_underwater,
    chart_category_mix as _chart_category_mix,
    chart_monthly_heatmap as _chart_monthly_heatmap,
    chart_rolling as _chart_rolling,
    chart_fund_detail as _chart_fund_detail,
    chart_monthly_bars as _chart_monthly_bars,
    chart_cmp_growth as _chart_cmp_growth,
    chart_cmp_periods as _chart_cmp_periods,
    chart_cmp_scatter as _chart_cmp_scatter,
    chart_cmp_drawdown as _chart_cmp_drawdown,
    chart_cmp_radar as _chart_cmp_radar,
)

# Geriye uyumluluk: eski `report._build_portfolio` vb. adları koru
# (testler ve dış çağrılar tefas.allocation'a geçene kadar).
_build_portfolio = allocation.build_portfolio
_portfolio_expected = allocation.portfolio_expected
_new_opportunities = allocation.new_opportunities
_backtest_summary_from_csv = allocation.backtest_summary_from_csv
_walk_forward_summary = validation.summarize_walk_forward_csv

NAVY = colors.HexColor("#13294b")
BLUE = colors.HexColor("#1f5fb0")
LIGHT = colors.HexColor("#eef3fb")
LIGHTER = colors.HexColor("#f7f9fd")
GREY = colors.HexColor("#6b7785")
LINE = colors.HexColor("#d4dbe6")
GOOD = colors.HexColor("#e3f4ec")   # en-iyi hücre vurgusu (açık yeşil)


class _OutlineDoc(SimpleDocTemplate):
    """"Section" stilindeki başlıklardan PDF outline (yer imi) + TOC girdisi üretir.

    Yer imi anahtarı başlık metninden deterministik türetilir ki `multiBuild`
    geçişleri arasında TOC bağlantıları geçerli kalsın.
    """

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "Section":
            text = flowable.getPlainText()
            key = "sec-%08x" % (zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF)
            self.canv.bookmarkPage(key)
            try:
                self.canv.addOutlineEntry(text, key, level=0, closed=False)
            except Exception:  # noqa: BLE001 — yinelenen başlık outline'ı düşürmesin
                pass
            self.notify("TOCEntry", (0, text, self.page, key))


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


def _fund_detail_flowables(row, combined, scored_df, theme_meds, styles, chart_dir, rf, color):
    """Tek fon için tam sayfa detay: büyük grafik, aylık barlar, akran kıyas tablosu."""
    code = str(row["Fon Kodu"])
    theme = row.get("Tema") if pd.notna(row.get("Tema")) else fund_theme(row.get("Fon Adi"))

    # Akran patikası: yeterli fon varsa tema medyanı, yoksa evren medyanı.
    bench, blabel = None, "Evren medyanı"
    if scored_df is not None and "Tema" in scored_df.columns:
        peers = scored_df.loc[scored_df["Tema"] == theme, "Fon Kodu"].astype(str).tolist()
        if len(peers) >= config.THEME_MIN_FUNDS:
            bench = themes.theme_median_growth(combined, codes=peers)
            blabel = f"Tema medyanı ({len(peers)} fon)"
    if bench is None:
        bench = themes.theme_median_growth(combined)
        blabel = "Evren medyanı"

    big = _chart_fund_detail(combined, code, chart_dir / f"detail_{code}.png", color, bench, blabel)
    bars = _chart_monthly_bars(combined, code, chart_dir / f"mbars_{code}.png")

    rf_flag = "✓ rf üzeri" if bool(row.get("Rf_Ustu")) else f"— rf (%{rf:.0f}) altı"
    thin = pd.notna(row.get("Veri_Noktasi_Sayisi")) and row.get("Veri_Noktasi_Sayisi") < config.TRADING_DAYS_PER_YEAR
    thin_note = " &nbsp;|&nbsp; * 1 yıldan kısa geçmiş" if thin else ""
    flow = [Paragraph(f"FON DETAYI — {_code_label(row)}", styles["Section"]),
            Paragraph(f"{short_name(row.get('Fon Adi'), 95)} &nbsp;|&nbsp; Tema: {theme} &nbsp;|&nbsp; "
                      f"{rf_flag}{thin_note}", styles["Body"]), Spacer(1, 2 * mm)]

    imgs = []
    if big:
        imgs.append(Image(big, width=155 * mm, height=82 * mm))
    if bars:
        imgs.append(Image(bars, width=95 * mm, height=81 * mm))
    if imgs:
        img_tbl = Table([imgs], colWidths=[158 * mm, 98 * mm][: len(imgs)])
        img_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
        flow += [img_tbl, Spacer(1, 3 * mm)]

    # Akran kıyas tablosu: fon vs. tema medyanı vs. evren medyanı
    metric_rows = [("Yıllık Getiri", "Yillik_Getiri", lambda v: pct(v)),
                   ("Volatilite", "Yillik_Volatilite", lambda v: pct(v)),
                   ("Sharpe", "Sharpe_Orani", lambda v: fmt(v, 2)),
                   ("Sortino", "Sortino_Orani", lambda v: fmt(v, 2)),
                   ("Max Drawdown", "Max_Drawdown", lambda v: pct(v)),
                   ("VaR %95 (gün)", "VaR_95", lambda v: pct(v)),
                   ("Reel Getiri", "Reel_Getiri_1Y", lambda v: pct(v)),
                   ("AUM (mn TL)", "Fon_Toplam_Deger_Milyon_TL", lambda v: fmt(v, 0))]
    tmed = theme_meds.loc[theme] if (theme_meds is not None and theme in theme_meds.index) else None
    headers = ["Metrik", "Fon", "Tema Medyanı", "Evren Medyanı"]
    cw = [42 * mm, 30 * mm, 32 * mm, 32 * mm]
    trows = []
    for label, colname, f in metric_rows:
        tval = f(tmed.get(colname)) if tmed is not None and colname in tmed.index else "—"
        uval = f(pd.to_numeric(scored_df[colname], errors="coerce").median()) \
            if (scored_df is not None and colname in scored_df.columns) else "—"
        trows.append([Paragraph(label, styles["CellB"]), Paragraph(f(row.get(colname)), styles["Cell"]),
                      Paragraph(tval, styles["Cell"]), Paragraph(uval, styles["Cell"])])
    n_peers = int(tmed["Fon_Sayisi"]) if (tmed is not None and "Fon_Sayisi" in tmed.index) else 0
    rel = row.get("Tema_Rel_Skor")
    rel_txt = (f"Tema içi getiri yüzdeliği: <b>{fmt(rel, 0)} / 100</b> ({n_peers} fon)"
               if pd.notna(rel) else f"Tema içi yüzdelik: — (temada {config.THEME_MIN_FUNDS} fondan az)")
    flow += [_make_table(headers, trows, cw, styles, align_right_from=1),
             Spacer(1, 2 * mm), Paragraph(rel_txt, styles["BodySm"]), PageBreak()]
    return flow


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
    # rf bayrağı ve tema yüzdeliği kartta değil, fonun DETAY sayfasında gösterilir
    # (kart 6 satırda kalır ki 6 künye tek sayfaya sığsın).
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
    chart_dir = Path(tempfile.mkdtemp(prefix=f"_{out_path.stem}_charts_", dir=out_path.parent))

    df = scored.copy()
    extra = [c for c in ["Fon_Toplam_Deger_Milyon_TL", "Fon_Yasi_Yil", "Fon_Kurulus_Tarihi",
                         "VaR_95", "CVaR_95", "Reel_Getiri_1Y", "Veri_Kalitesi"]
             if c in metrics.columns and c not in df.columns]
    if extra:
        df = df.merge(metrics[["Fon Kodu"] + extra], on="Fon Kodu", how="left")
    df = allocation.add_decision_flags(df)

    n_funds = len(df)
    # Ortak fiyat pivotu: pivot gerektiren grafik üreticilerine BİR KEZ kurulup
    # geçirilir (önceden her üretici ~yüzbinlerce satırı yeniden pivotluyordu).
    pivot = price_pivot(combined) if combined is not None and len(combined) else None
    df["_tema"] = df["Fon Adi"].map(fund_theme)
    # Öneriler yalnızca UYGUN fonlardan (AUM/yaş kriterlerini geçen); sıralama
    # ise tüm evren üzerinden yapıldı (bkz. metrics.compute_metrics). rf artık
    # eleme değil bilgilendirici bayrak (Rf_Ustu). Uygun yoksa tüm evrene düşülür.
    elig = df[df["Oneri_Uygun"]].copy() if "Oneri_Uygun" in df.columns else (
        df[df["Uygun"]].copy() if "Uygun" in df.columns else df.copy())
    if elig.empty:
        elig = df.copy()
    n_elig = int(df["Oneri_Uygun"].sum()) if "Oneri_Uygun" in df.columns else (
        int(df["Uygun"].sum()) if "Uygun" in df.columns else n_funds)
    styles = _styles()
    today = datetime.now().strftime("%d.%m.%Y")
    mac = config.macro()
    # Config dosyasında bulunmayıp koddaki varsayılana düşen oranlar kapakta işaretlenir.
    dflt = lambda key: " (varsayılan)" if key in mac.defaults_used else ""
    story = []

    # 1. Kapak — tüm içerik tek sayfada kalsın diye KeepTogether ile sarılır.
    cover_items = [
        Spacer(1, 48 * mm), Paragraph("TEFAS", styles["CoverTitle"]),
        Paragraph("PREMİUM YATIRIM RAPORU", styles["CoverTitle"]), Spacer(1, 6 * mm),
        Paragraph(f"{paths.fund_name} Fonları &nbsp;|&nbsp; Kantitatif Analiz, Risk Profilleme & Portföy Önerileri", styles["CoverSub"]),
        Spacer(1, 12 * mm),
        Paragraph(f"Rapor Tarihi: {today}<br/>Analiz Edilen Fon Sayısı: {n_funds}<br/>"
                  f"Risksiz Faiz Oranı (Benchmark): %{risk_free_rate:.1f}{dflt('risk_free_rate') if risk_free_rate == mac.risk_free_rate else ''}<br/>"
                  f"Enflasyon (TÜFE): %{mac.inflation_rate:.0f}{dflt('inflation_rate')} &nbsp;|&nbsp; "
                  f"Politika Faizi: %{mac.policy_rate:.0f}{dflt('policy_rate')}", styles["CoverInfo"]),
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

    # 1b. İçindekiler — girdiler _OutlineDoc.afterFlowable'dan beslenir; sayfa
    # numaraları otursun diye belge multiBuild ile (2+ geçiş) kurulur. Başlık
    # bilerek "Section" stili DEĞİL: kendisi TOC'a girmesin.
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("TOCEntry", fontName=FONT, fontSize=10,
                                      leading=17, leftIndent=4, textColor=NAVY)]
    story += [Paragraph("İÇİNDEKİLER", ParagraphStyle("TocHead", parent=styles["Section"])),
              Spacer(1, 3 * mm), toc, PageBreak()]

    # 2. Gösterge paneli (dashboard)
    avg = lambda c: df[c].mean() if c in df.columns else np.nan
    med = lambda c: df[c].median() if c in df.columns else np.nan
    top_overall = elig.nlargest(5, "Overall_Score")
    top10_codes = elig.nlargest(10, "Overall_Score")["Fon Kodu"].tolist()
    # Fon → renk eşlemesi: ilk 10 fon, tüm grafiklerde (büyüme, detay, sparkline
    # vurguları) aynı rengi taşır. Renk fona bağlıdır, sıralamaya değil.
    color_map = {code: FUND_PALETTE[i % len(FUND_PALETTE)] for i, code in enumerate(top10_codes)}
    ret_all = pd.to_numeric(df["Yillik_Getiri"], errors="coerce")
    real_all = pd.to_numeric(df.get("Reel_Getiri_1Y"), errors="coerce") if "Reel_Getiri_1Y" in df.columns else None
    pf_ = lambda m: f"{m * 100:.0f}%"
    cards = [
        (f"{n_funds:,}", "Analiz edilen fon"),
        (f"{n_elig:,}", "Ana öneriye uygun"),
        (pct(avg("Yillik_Getiri")), "Ort. yıllık getiri"),
        (pct(avg("Yillik_Volatilite")), "Ort. volatilite"),
        (fmt(avg("Sharpe_Orani"), 2), "Ort. Sharpe"),
        (pct(med("Max_Drawdown")), "Medyan Max DD"),
        (pf_((ret_all > mac.inflation_rate).mean()), "Enflasyonu geçen"),
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
    bt_validation = _walk_forward_summary(paths.backtest_csv)
    bt_sum = bt_validation.table
    story.append(PageBreak())
    story.append(Paragraph("MODEL DOGRULAMA - WALK-FORWARD", styles["Section"]))
    if bt_validation.available:
        has_turnover = "Turnover" in bt_sum.columns
        bt_headers = ["Ufuk", "Kat", "Portfoy Ort.", "Evren Ort.", "Ort. Fark",
                      "Medyan Fark", "Isabet"] + (["Turnover"] if has_turnover else [])
        bt_rows = [[Paragraph(f"{int(r['Ufuk_Ay'])} ay", styles["CellB"]),
                    Paragraph(fmt(r["Kat_Sayisi"], 0), styles["Cell"]),
                    Paragraph(pct(r["Portfoy_Ort"]), styles["Cell"]),
                    Paragraph(pct(r["Evren_Ort"]), styles["Cell"]),
                    Paragraph(pct(r["Ort_Fark"]), styles["Cell"]),
                    Paragraph(pct(r["Medyan_Fark"]), styles["Cell"]),
                    Paragraph(pct(r["Isabet_Orani"] * 100), styles["Cell"])] +
                   ([Paragraph(pct(r["Turnover"] * 100), styles["Cell"])] if has_turnover else [])
                   for _, r in bt_sum.iterrows()]
        widths = [18 * mm, 14 * mm, 25 * mm, 25 * mm, 24 * mm, 27 * mm, 20 * mm]
        if has_turnover:
            widths.append(20 * mm)
        story += [
            Paragraph("Bu tablo, onerilen skorlama ve portfoy kurma kuralinin her ay sonunda yalnizca "
                      "o tarihe kadar bilinen veriyle secim yaptiginda sonraki donemde evren ortalamasini "
                      "asip asmadigini gosterir. Kat sayisi sinirli oldugu icin istatistiksel kanit degil; "
                      "modelin ileriye donuk sinyal tasiyip tasimadigina dair disiplinli bir saglamadir.",
                      styles["BodySm"]),
            _make_table(bt_headers, bt_rows, widths, styles, align_right_from=1),
            Spacer(1, 2 * mm),
            Paragraph(f"Kaynak: {paths.backtest_csv.name}. Skor/profil agirliklari degistirildiginde "
                      "bu backtest yeniden calistirilmali ve PDF bu ozetle guncellenmelidir.",
                      styles["Disclaimer"]),
        ]
    else:
        story += [
            Paragraph(bt_validation.message, styles["Body"]),
            Paragraph("Bu rapor, model kalitesi icin walk-forward CSV'si olmadan uretilmistir. "
                      "`tefas backtest` calistirildiginda ayni bolum kat sayisi, 1A/3A/6A "
                      "sonuclari, ortalama fark, medyan fark ve isabet oranini gosterecektir.",
                      styles["Disclaimer"]),
        ]
    story.append(PageBreak())

    # 3. Karar özeti
    kpi_rows = [["Analiz edilen fon", str(n_funds), "Ort. yıllık getiri", pct(avg("Yillik_Getiri"))],
                ["Ort. volatilite", pct(avg("Yillik_Volatilite")), "Ort. Sharpe", fmt(avg("Sharpe_Orani"), 2)],
                ["Ort. Max Drawdown", pct(avg("Max_Drawdown")), "Ort. composite skor", fmt(avg("Overall_Score"), 1)]]
    kpi_tbl = Table([[Paragraph(f"<b>{a}</b>", styles["Cell"]), Paragraph(b, styles["Cell"]),
                      Paragraph(f"<b>{c}</b>", styles["Cell"]), Paragraph(d, styles["Cell"])] for a, b, c, d in kpi_rows],
                    colWidths=[55 * mm, 40 * mm, 55 * mm, 40 * mm])
    kpi_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                                 ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [Paragraph("KARAR ÖZETİ", styles["Section"]), kpi_tbl, Spacer(1, 4 * mm),
              Paragraph(f"<b>Öne çıkanlar:</b> Composite skora göre en iyi 5 fon: <b>{', '.join(top_overall['Fon Kodu'].tolist())}</b>. "
                        f"Bu fonlar; risk-ayarlı getiri (Sharpe/Sortino), drawdown kontrolü, getiri ve likidite eksenlerinin "
                        f"yüzdelik-sıra bileşimiyle seçilmiştir. Veri kalitesi şüpheli (> %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} "
                        f"tek-günlük sıçrama) fonlar analiz dışında bırakılmıştır.", styles["Body"]), Spacer(1, 3 * mm)]

    # ── Benchmark karşılaştırması (#2): UYGUN fonlar (rf'yi geçenler) üzerinden;
    #    asıl soru enflasyon/politika faizi ve reel getiri.
    m_infl = int((elig["Yillik_Getiri"] > mac.inflation_rate).sum())
    m_pol = int((elig["Yillik_Getiri"] > mac.policy_rate).sum())
    has_real = "Reel_Getiri_1Y" in elig.columns
    m_real_pos = int((elig["Reel_Getiri_1Y"] > 0).sum()) if has_real else 0
    avg_real = elig["Reel_Getiri_1Y"].mean() if has_real else np.nan
    p = lambda k: f"{k} / {n_elig} (%{k / n_elig * 100:.0f})" if n_elig else "—"
    bench_rows = [
        [f"Enflasyonu (%{mac.inflation_rate:.0f}) geçen", p(m_infl),
         f"Politika faizini (%{mac.policy_rate:.0f}) geçen", p(m_pol)],
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
    rf_note = f" Bunların {int(elig['Rf_Ustu'].sum())} tanesi rf (%{risk_free_rate:.0f}) üzeri getiri sağlıyor." \
        if "Rf_Ustu" in elig.columns else ""
    story += [Paragraph(f"Benchmark Karşılaştırması (ana öneriye uygun {n_elig} fon üzerinden):{rf_note}",
                        styles["SubSec"]),
              bench_tbl, Spacer(1, 2 * mm)]

    # ── Veri kapsamı uyarısı (#1)
    n_thin = int((df["Veri_Noktasi_Sayisi"] < config.TRADING_DAYS_PER_YEAR).sum())
    med_days = int(df["Veri_Noktasi_Sayisi"].median()) if len(df) else 0
    story += [Paragraph(
        f"<b>Veri kapsamı:</b> medyan gözlem {med_days} iş günü. Analiz edilen fonların "
        f"<b>{n_thin}</b> tanesinin 1 yıldan ({config.TRADING_DAYS_PER_YEAR} iş günü) kısa fiyat geçmişi var; "
        f"bu fonlarda yıllık getiri <b>daha kısa bir pencereden yıllıklandırıldığı</b> için (ve Sharpe) "
        f"gürültülüdür — tablolarda <b>*</b> ile işaretlenir ve skorlamada akran medyanına doğru "
        f"güvenilirlik-düzeltmesi uygulanır (bkz. Metodoloji).",
        styles["BodySm"]), Spacer(1, 2 * mm)]

    flag_defs = [
        ("rf altı", "Rf_Ustu", lambda s: int((~s.fillna(False).astype(bool)).sum())),
        ("reel negatif", "Reel_Getiri_1Y", lambda s: int((pd.to_numeric(s, errors="coerce") <= 0).sum())),
        ("kısa geçmiş", "Kisa_Gecmis", lambda s: int(s.fillna(False).astype(bool).sum())),
        ("düşük AUM", "Dusuk_AUM", lambda s: int(s.fillna(False).astype(bool).sum())),
        ("yüksek drawdown", "Yuksek_Drawdown", lambda s: int(s.fillna(False).astype(bool).sum())),
        ("düşük oynaklık ama rf altı", "Dusuk_Vol_Rf_Alti", lambda s: int(s.fillna(False).astype(bool).sum())),
    ]
    flag_rows = []
    for label, col, counter in flag_defs:
        if col in df.columns:
            flag_rows.append([Paragraph(label, styles["CellB"]),
                              Paragraph(fmt(counter(df[col]), 0), styles["Cell"])])
    if flag_rows:
        story += [
            Paragraph("UYARI BAYRAKLARI", styles["Section"]),
            Paragraph("Bu bayraklar fonu otomatik olarak diskalifiye etmez; karar masasındaki ana risk/uygunluk notlarını görünür kılar.",
                      styles["BodySm"]),
            _make_table(["Bayrak", "Fon Sayısı"], flag_rows, [70 * mm, 28 * mm], styles, align_right_from=1),
            Spacer(1, 3 * mm),
        ]

    img = _chart_top_returns(elig, chart_dir / "top_returns.png")
    if img:
        story.append(Image(img, width=200 * mm, height=87 * mm))
    story.append(PageBreak())

    # 4. En iyi fonlar
    rf_mark = lambda r: "✓" if bool(r.get("Rf_Ustu")) else "—"
    headers = ["Kod", "Fon Adı", "Skor", "Yıl. Get.", "Volat.", "Sharpe", "Max DD", "rf+", "Bayraklar", "Gerekçe"]
    cw = [13 * mm, 42 * mm, 13 * mm, 16 * mm, 15 * mm, 14 * mm, 15 * mm, 9 * mm, 42 * mm, 55 * mm]
    rows = [[Paragraph(_code_label(r), styles["CellB"]), Paragraph(short_name(r["Fon Adi"], 42), styles["Cell"]),
             Paragraph(fmt(r.get("Overall_Score"), 1), styles["Cell"]), Paragraph(pct(r.get("Yillik_Getiri")), styles["Cell"]),
             Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]), Paragraph(fmt(r.get("Sharpe_Orani"), 2), styles["Cell"]),
             Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"]),
             Paragraph(rf_mark(r), styles["Cell"]),
             Paragraph(short_name(r.get("Karar_Bayraklari", "temiz"), 52), styles["Cell"]),
             Paragraph(build_rationale(r), styles["Rationale"])] for _, r in elig.nlargest(12, "Overall_Score").iterrows()]
    story += [Paragraph("EN İYİ FONLAR — GENEL SIRALAMA", styles["Section"]),
              Paragraph("Composite skora göre ilk 12 <b>uygun</b> fon (AUM/yaş kriterlerini geçen) ve her biri için kısa yatırım gerekçesi. "
                        f"<b>rf+</b> sütunu yıllık getirinin risksiz faizi (%{risk_free_rate:.0f}) aşıp aşmadığını gösterir — bilgilendirici bayraktır, eleme kriteri değildir.", styles["BodySm"]),
              _make_table(headers, rows, cw, styles, align_right_from=2),
              Spacer(1, 2 * mm),
              Paragraph("* 1 yıldan kısa fiyat geçmişi — yıllık getiri daha kısa pencereden yıllıklandırılır, gürültülüdür.", styles["Disclaimer"])]

    universe_bench = themes.theme_median_growth(combined)
    growth_chart = _chart_growth_history(combined, top_overall["Fon Kodu"].tolist(), chart_dir / "growth.png",
                                         color_map=color_map, benchmark=universe_bench, pivot=pivot)
    if growth_chart:
        story += [Spacer(1, 4 * mm),
                  Image(growth_chart, width=236 * mm, height=110 * mm)]
    story.append(PageBreak())

    # 4b. Aylık getiri takvimi (ısı haritası)
    hm = _chart_monthly_heatmap(combined, top10_codes, chart_dir / "monthly_hm.png", pivot=pivot)
    if hm:
        n_hm_rows = len(top10_codes) + 1
        hm_h = min((0.42 * n_hm_rows + 1.15) / 9.8 * 236, 150)
        story += [Paragraph("AYLIK GETİRİ TAKVİMİ — İLK 10", styles["Section"]),
                  Paragraph("Composite skora göre ilk 10 uygun fonun ay-ay getirisi ve tüm evrenin ay medyanı (son satır). "
                            "Yeşil pozitif, kırmızı negatif ayları gösterir; gri hücrelerde fonun o ay verisi yoktur. "
                            "Tutarlı fonlar satır boyunca kesintisiz yeşil ton bırakır.", styles["BodySm"]),
                  Image(hm, width=236 * mm, height=hm_h * mm), PageBreak()]

    # 4c. Yuvarlanan getiri & volatilite
    roll = _chart_rolling(combined, top_overall["Fon Kodu"].tolist(), chart_dir / "rolling.png",
                          rf=risk_free_rate, color_map=color_map, pivot=pivot)
    if roll:
        story += [Paragraph("YUVARLANAN 63 GÜNLÜK GETİRİ & VOLATİLİTE — İLK 5", styles["Section"]),
                  Paragraph("Üst panel: 63 işlem günlük pencereden yıllıklandırılmış getiri — kesikli gri çizgi risksiz faiz. "
                            "Alt panel: aynı pencerede yıllıklandırılmış volatilite. Performansın döneme mi yayıldığını yoksa "
                            "tek bir sıçramadan mı geldiğini ve risk rejimindeki değişimleri gösterir.", styles["BodySm"]),
                  Image(roll, width=226 * mm, height=118 * mm), PageBreak()]

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

    # 5b. Fon detay sayfaları — ilk 6 öneri, her fon tam sayfa
    detail_cols = ["Yillik_Getiri", "Yillik_Volatilite", "Sharpe_Orani", "Sortino_Orani",
                   "Max_Drawdown", "VaR_95", "Reel_Getiri_1Y", "Fon_Toplam_Deger_Milyon_TL"]
    theme_meds = themes.theme_medians(df, detail_cols) if "Tema" in df.columns else None
    story.append(Paragraph("FON DETAYLARI", styles["Section"]))
    story.append(Paragraph("İlk 6 öneri için tam sayfa fon kırılımı: büyüme, drawdown, aylık getiriler ve tema/evren kıyası.",
                           styles["BodySm"]))
    story.append(PageBreak())
    for _, r in card_rows_src.iterrows():
        story += _fund_detail_flowables(r, combined, df, theme_meds, styles, chart_dir,
                                        risk_free_rate, color_map.get(str(r["Fon Kodu"])))

    # 6. Risk profilleri
    story.append(Paragraph("RİSK PROFİLİNE GÖRE ÖNERİLER", styles["Section"]))
    profile_defs = [
        ("Conservative", "MUHAFAZAKÂR", "Sermaye koruması önceliklidir: düşük volatilite, düşük drawdown, yüksek istikrar ve mevduatı geçen getiri. Genellikle para piyasası ve kısa vadeli borçlanma fonları öne çıkar."),
        ("Balanced", "DENGELİ", "En iyi risk-ayarlı getiri (Sortino/Calmar) orta volatilite bandında. Aşağı yönlü riske duyarlıdır."),
        ("Moderate", "ORTA", "Sharpe ağırlıklı dengeli büyüme: risk-ayarlı getiri önceliklidir; orta volatilite bandı, getiri ve istikrar dengesiyle desteklenir."),
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
                 for _, r in elig.nlargest(6, col).iterrows()]
        block += [_make_table(prof_headers, prows, prof_cw, styles, align_right_from=3), Spacer(1, 3 * mm)]
        story.append(KeepTogether(block))
    story.append(PageBreak())

    # 6b. Yeni fırsatlar — 2–6 ay önce kurulmuş genç fonlar
    newops = _new_opportunities(df, combined)
    if len(newops):
        top_new = newops.head(8)
        fmt_date = lambda v: pd.to_datetime(v).strftime("%d.%m.%Y") if pd.notna(v) else "—"
        no_headers = ["Kod", "Fon Adı", "Tema", "Kuruluş", "Yaş (ay)", "AUM (mn)",
                      "1A", "3A", "Volat.", "Max DD", "Poz. Gün", "Fırsat"]
        no_cw = [13 * mm, 51 * mm, 27 * mm, 19 * mm, 14 * mm, 16 * mm,
                 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 12 * mm]
        no_rows = [[Paragraph(_code_label(r), styles["CellB"]),
                    Paragraph(short_name(r["Fon Adi"], 44), styles["Cell"]),
                    Paragraph(str(r.get("Tema")) if pd.notna(r.get("Tema")) else fund_theme(r["Fon Adi"]), styles["Cell"]),
                    Paragraph(fmt_date(r.get("Fon_Kurulus_Tarihi")), styles["Cell"]),
                    Paragraph(fmt(r.get("Yas_Ay"), 1), styles["Cell"]),
                    Paragraph(fmt(r.get("Fon_Toplam_Deger_Milyon_TL"), 0), styles["Cell"]),
                    Paragraph(pct(r.get("Getiri_1A")), styles["Cell"]),
                    Paragraph(pct(r.get("Getiri_3A")), styles["Cell"]),
                    Paragraph(pct(r.get("Yillik_Volatilite")), styles["Cell"]),
                    Paragraph(pct(r.get("Max_Drawdown")), styles["Cell"]),
                    Paragraph(pct(r.get("Pozitif_Gun_Orani"), 0), styles["Cell"]),
                    Paragraph(fmt(r.get("Firsat_Skoru"), 1), styles["CellB"])]
                   for _, r in top_new.iterrows()]
        story += [
            Paragraph("YENİ FIRSATLAR — YENİ KURULAN FONLAR", styles["Section"]),
            Paragraph(f"Verideki ilk fiyat gününe göre <b>2–6 ay önce</b> kurulmuş {len(newops)} genç fon tarandı; "
                      "aşağıda Fırsat Skoruna göre en iyileri listelenir. Bu fonlar kısa geçmişleri nedeniyle ana "
                      "öneri listelerine henüz giremez; erken dönem performansı güçlü olanları radara almak için ayrı "
                      "değerlendirilir. <b>Fırsat Skoru</b> yalnızca bu kohort içindeki yüzdelik sıralardan hesaplanır: "
                      "3 aylık getiri (%30), 1 aylık getiri (%25), pozitif gün oranı (%20), düşük drawdown (%15) ve "
                      "AUM/likidite (%10). Yıllıklandırılmış getiri/Sharpe bu yaşta gürültülü veya hesaplanamaz "
                      "olduğundan kullanılmaz.", styles["BodySm"]),
            _make_table(no_headers, no_rows, no_cw, styles, align_right_from=4),
            Spacer(1, 2 * mm),
            Paragraph("* Tüm yeni fonlar 1 yıldan kısa fiyat geçmişine sahiptir; metrikler kısa pencereden gelir ve "
                      "gürültülüdür. Kuruluş tarihi, fonun verideki ilk fiyat gününe dayanan bir yaklaşımdır. Kısa "
                      "geçmiş, kalıcı performansın kanıtı değildir — bu bölüm bir izleme listesidir, öneri değildir.",
                      styles["Disclaimer"])]
        new_growth = _chart_growth_history(combined, top_new["Fon Kodu"].astype(str).tolist()[:5],
                                           chart_dir / "new_opportunities.png",
                                           benchmark=universe_bench, pivot=pivot,
                                           title="Yeni Fırsat Fonlarının Kümülatif Büyümesi (ortak dönem)")
        if new_growth:
            story += [Spacer(1, 3 * mm), Image(new_growth, width=226 * mm, height=106 * mm)]
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
                f"<b>Kovaryans penceresi:</b> en az {risk['effective_days']} ortak gün · "
                f"büzülme δ={risk['shrinkage']:.2f}"
                + (f" · veri yetersiz: {', '.join(risk['dropped_codes'])}" if risk['dropped_codes'] else "")
                + "<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        else:
            risk_txt = (
                f"<b>Beklenen yıllık getiri (ağırlıklı):</b> %{exp_ret:.1f}<br/>"
                f"<b>Tahmini portföy volatilitesi:</b> %{vol_lo:.1f} – %{vol_hi:.1f} (çeşitlendirme bandı)<br/>"
                f"<b>Fon/tema sayısı:</b> {len(portfolio)} / {len({p['Tema'] for p in portfolio})}")
        story.append(Paragraph("Farkli risk profillerinden, her temadan en cok BIR fon secilen ornek bir portfoy "
                               "(tema tekligi walk-forward dogrulamasiyla secildi: tavan gevsedikce isabet monoton "
                               "dusuyor). Filtrelenmis evren az temaliysa bos profil slotlari en iyi kalan fonlarla "
                               "doldurulur; portfoy volatilitesi fonlarin gercek gunluk getiri kovaryansindan "
                               "hesaplanir.", styles["BodySm"]))
        pie = _chart_allocation(portfolio, chart_dir / "allocation.png")
        ph = ["Kod", "Fon Adı", "Profil", "Tema", "Ağırlık", "Risk Katk.", "Yıl. Get.", "Volat.", "Bayraklar"]
        pcw = [12 * mm, 38 * mm, 19 * mm, 25 * mm, 14 * mm, 17 * mm, 15 * mm, 15 * mm, 58 * mm]
        rc = risk.get("risk_contributions", {}) if risk is not None else {}
        prows = []
        for p in portfolio:
            code = str(p["Fon Kodu"])
            risk_contrib = rc.get(code)
            flags = str(p.get("Karar_Bayraklari") or "temiz")
            if risk_contrib is not None and (risk_contrib * 100.0) > float(p.get("Agirlik", 0)) + 5.0:
                flags = f"{flags}; yuksek risk katkisi"
            prows.append([Paragraph(code, styles["CellB"]), Paragraph(short_name(p["Fon Adi"], 40), styles["Cell"]),
                          Paragraph(p["Profil"], styles["Cell"]), Paragraph(p["Tema"], styles["Cell"]),
                          Paragraph(pct(p["Agirlik"], 1), styles["Cell"]),
                          Paragraph(pct(risk_contrib * 100.0) if risk_contrib is not None else "—", styles["Cell"]),
                          Paragraph(pct(p["Yillik_Getiri"]), styles["Cell"]),
                          Paragraph(pct(p["Yillik_Volatilite"]), styles["Cell"]),
                          Paragraph(short_name(flags, 70), styles["Cell"])])
        ptable = _make_table(ph, prows, pcw, styles, align_right_from=4)
        story += [ptable, Spacer(1, 3 * mm), Paragraph(risk_txt, styles["Body"])]
        if pie:
            story += [Spacer(1, 2 * mm), Image(pie, width=120 * mm, height=88 * mm)]

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
                          PageBreak(),
                          Paragraph("PORTFÖY RİSK KATKISI", styles["Section"]),
                          Paragraph("Ağırlık ile gerçek risk katkısı farklı şeylerdir: yüksek volatilite veya güçlü korelasyon "
                                    "taşıyan bir fon, portföy ağırlığından daha büyük risk payı yaratabilir.",
                                    styles["BodySm"]),
                          Image(rc_chart, width=236 * mm, height=126 * mm)]

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
        ("Composite Skor", "Sharpe (%25), Sortino (%15), düşük drawdown (%20), yıllık getiri (%20), tema-içi getiri yüzdeliği (%5), "
         "tutarlılık (%7,5) ve likidite/AUM (%7,5) eksenlerinin yüzdelik-sıra ağırlıklı bileşimi — getiri etkisi toplamda %25 "
         "(%20 mutlak + %5 akran-göreli). Sharpe ve Sortino yüksek korelasyonlu olduğundan toplam ağırlıkları sınırlandırılmıştır. "
         "Tutarlılık skoru pozitif gün/ay oranı ve aylık getiri dağılımına dayanır; drawdown ve Sortino'yu tekrar kullanmaz (çifte sayım yok). "
         "Yüzdelik-sıra skorları uç değerlere karşı dayanıklıdır ve <b>tüm evren</b> üzerinden hesaplanır."),
        ("Kısa Geçmiş Düzeltmesi (Shrinkage)", f"1 yıldan kısa pencereden yıllıklandırılan getiri gürültülüdür. Skorlamada getiri, "
         f"güvenilirlik ağırlığı w = pencere günü / {config.RETURN_FULL_CREDIBILITY_DAYS} (en çok 1) ile fonun kendi getirisi ve akran "
         f"(tema, en az {config.THEME_MIN_FUNDS} fon; yoksa evren) medyanının bileşimine çekilir. {config.RETURN_FULL_CREDIBILITY_DAYS}+ "
         "gün geçmişi olan fonlarda düzeltme sıfırdır. Tablolarda gösterilen getiriler HAM değerlerdir; düzeltme yalnızca skor girdisidir."),
        ("Benchmark (Endeks) Metrikleri", "Beta, Jensen Alpha, Tracking Error ve Information Ratio YALNIZCA gerçek bir dış endeks "
         "serisi mevcutsa hesaplanır (<b>Dataset/benchmarks/</b>: XU100, gram altın, USD/TRY vb.; tema → benchmark eşlemesi "
         "benchmarks.py'dedir). Vekil benchmark (fon ortalaması) kullanılmaz — CAPM/aktif-getiri yorumunu geçersiz kılar. Bu metrikler "
         "bilgilendirme amaçlıdır; skor bileşimine dahil edilmez."),
        ("Akran (Tema) Kıyası", "Skorlamada harici endeks kullanılmaz; akran kıyası veri-seti içidir. Her fon, adından türetilen temasına atanır ve "
         f"temasındaki (≥ {config.THEME_MIN_FUNDS} fon) getiri yüzdeliği <b>tema-içi skor</b> olarak hesaplanır. Büyüme grafiklerindeki "
         "kesikli gri çizgi evren/tema medyan patikasıdır (günlük medyan getiriden bileşiklenir)."),
        ("Sıralama vs. Seçim", "Skorlar tüm (veri-kalitesi geçerli) evren üzerinden hesaplanır; AUM / yaş kriterleri sıralamayı bozmadan "
         "bir <b>uygunluk</b> filtresi olarak uygulanır. Risksiz faiz artık eleme kriteri DEĞİLDİR: rf üzeri getiri sağlayan fonlar "
         "tablolarda <b>rf+</b> bayrağıyla işaretlenir. Öneri tabloları yalnızca uygun fonları listeler; risk-getiri haritası bağlam "
         "için tüm evreni gösterir."),
        ("Yeni Fırsatlar Taraması", "Verideki ilk fiyat günü (kuruluş tarihi vekili) rapor tarihinden 2–6 ay önce olan genç fonlar "
         "ayrı bir bölümde taranır. Fırsat Skoru bu kohortun KENDİ İÇİNDEKİ yüzdelik sıralardan hesaplanır: 3A getiri (%30), "
         "1A getiri (%25), pozitif gün oranı (%20), düşük drawdown (%15), AUM (%10). Yıllıklandırılmış getiri/Sharpe bu yaşta "
         "hesaplanamaz veya aşırı gürültülü olduğundan kullanılmaz. Veri setinin başlangıcına yapışık seriler (fon aslında daha "
         "yaşlı olabilir) elenir. Bölüm bir izleme listesidir; kısa geçmiş nedeniyle bu fonlar ana öneri listelerine dahil edilmez."),
        ("Risk-Ayarlı Metrikler & Winsorizasyon", "Sharpe = (Getiri − Rf) / Volatilite; Sortino aşağı yönlü sapmayı; Calmar maksimum "
         f"drawdown'u esas alır. Volatilite ve Sortino, ±%{config.DAILY_RETURN_CLIP:.0f} winsorize edilmiş günlük getirilerle hesaplanır "
         "(ikinci moment tahminini veri hatalarına karşı stabilize eder); Max Drawdown, VaR/CVaR, çarpıklık ve en iyi/kötü gün ise "
         "HAM getirilerle hesaplanır — kuyruk metrikleri gerçek kuyrukları görmelidir. Bu ayrım bilinçli bir tasarımdır."),
        ("Portföy Riski", "Örnek portföyün volatilitesi fonların gerçek günlük getiri kovaryansından σ = √(w'·Σ·w) ile hesaplanır. "
         "Kovaryans <b>ikili (pairwise)</b> tahmin edilir (her fon çifti kendi ortak gözlemlerini kullanır; tek bir kısa geçmişli fon "
         "tüm matrisin penceresini kırpmaz) ve küçük örneklem hatasına karşı sabit-korelasyon hedefine <b>büzülür</b> (Ledoit-Wolf tarzı; "
         "δ raporda gösterilir). En kısa ikili tahmin penceresi 'kovaryans penceresi' olarak raporlanır. "
         "Risk katkısı RC_i = w_i·(Σw)_i / (w'·Σ·w) her fonun riske gerçek payını, sualtı eğrisi ise tarihsel drawdown'u gösterir."),
        ("Risksiz Faiz (Rf) Varsayımı", f"Rf = %{risk_free_rate:.1f} — <b>tefas.config.json</b> dosyasından okunur ve gözlemlenebilir bir "
         "TL para-piyasası getirisini (mevduat/TLREF benzeri) yansıtacak şekilde kullanıcı tarafından belirlenmelidir. Sharpe, Sortino, "
         "Calmar ve 'Fazla Getiri'de aşım eşiği olarak kullanılır; Sortino'daki günlük eşik yıllık oranın <b>geometrik</b> günlük "
         "eşdeğeridir ((1+rf)^(1/252)−1). Rf, politika faizinin belirgin üzerinde seçilirse fonların çoğunun aşım getirisi negatife "
         "döner ve oran-tabanlı metrikler 'en az kötü'yü sıralar; bu durumda mutlak getiri/volatilite eksenleri daha bilgilendiricidir."),
        ("Veri Kalitesi", f"Tek günde > %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} fiyat hareketi yapan fonlar şüpheli kabul edilip analizden çıkarılır."),
        ("Reel Getiri & Vergi", f"Reel getiri Fisher denklemiyle enflasyondan (%{mac.inflation_rate:.0f} TÜFE) arındırılır. "
         "<b>Net getiri yalnızca yönetim ücreti düşülerek</b> verilir; stopaj/işlem vergileri tutuş süresi ve fon tipine bağlı olduğundan "
         "(bu veri setinde yok) modellenmez. Enflasyon, politika faizi ve yönetim ücreti oranları <b>tefas.config.json</b> dosyasından okunur."),
        ("Survivorship Bias", "Analiz yalnızca platformda hâlen aktif olan fonları kapsar. Kapanmış, birleşmiş veya tasfiye edilmiş "
         "fonlar veri setinde bulunmadığından geçmiş performans istatistikleri iyimser yönde sapabilir (survivorship bias)."),
    ]
    for title, body in method:
        story += [Paragraph(title, styles["SubSec"]), Paragraph(body, styles["Body"])]
    story += [Spacer(1, 6 * mm),
              Paragraph("UYARI: Bu rapor yalnızca geçmiş TEFAS verisine uygulanan kantitatif modellere dayanır; yatırım tavsiyesi değildir. "
                        "Geçmiş performans gelecek getiriyi garanti etmez. İşlem maliyetleri ve vergi etkileri tam modellenmemiştir.", styles["Disclaimer"])]

    doc = _OutlineDoc(str(out_path), pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=12 * mm,
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

    # multiBuild: TOC sayfa numaraları ikinci geçişte oturur. Temp grafik
    # klasörü `finally` ile silinir: PDF kilitliyse (örn. görüntüleyicide açık)
    # build hata fırlatır — cleanup başarı/hata fark etmeksizin çalışmalı,
    # yoksa `_..._charts_XXXXXXXX` klasörleri Reports altında birikir.
    try:
        doc.multiBuild(story, onFirstPage=footer, onLaterPages=footer)
    finally:
        shutil.rmtree(chart_dir, ignore_errors=True)

    print(f"[OK] Konsolide premium rapor: {out_path}")
    return out_path


# ═════════════════════════════════════════════════════════════════════════════
#  KARŞILAŞTIRMA MODU  —  belirli fonları yan yana kıyaslayan rapor
# ═════════════════════════════════════════════════════════════════════════════

# metrik satırı: (etiket, (sütun, yön) | None, biçimlendirici)
_CMP_ROWS = [
    ("Tema", None, lambda r: fund_theme(r.get("Fon Adi"))),
    ("Yıllık Getiri", ("Yillik_Getiri", "high"), lambda r: pct(r.get("Yillik_Getiri"))),
    ("rf Üzeri Getiri", None, lambda r: "✓" if bool(r.get("Rf_Ustu")) else "—"),
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
                        out_path: Path | None = None,
                        universe_growth: pd.Series | None = None) -> Path:
    """Belirli fonları yan yana kıyaslayan PDF üretir; yolu döndürür.

    `universe_growth`: tüm evrenin baz-100 medyan büyüme patikası (pipeline
    tarafından alt kümeye inmeden hesaplanır). Verilmezse ve en az 3 fon
    kıyaslanıyorsa grubun kendi medyanı ("Grup medyanı") kullanılır.
    """
    paths = config.paths_for(fund_type)
    out_path = Path(out_path) if out_path else paths.comparison_pdf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chart_dir = Path(tempfile.mkdtemp(prefix=f"_{out_path.stem}_charts_", dir=out_path.parent))

    met = met.reset_index(drop=True)
    codes = met["Fon Kodu"].tolist()
    n = len(met)
    styles = _styles()
    today = datetime.now().strftime("%d.%m.%Y")
    mac = config.macro()
    dflt = lambda key: " (varsayılan)" if key in mac.defaults_used else ""
    color_map = {c: FUND_PALETTE[i % len(FUND_PALETTE)] for i, c in enumerate(codes)}

    # Benchmark patikası: evren medyanı; yoksa (>=3 fonda) grup medyanı.
    bench, bench_label = universe_growth, "Evren medyanı"
    if bench is None and n >= 3:
        bench = themes.theme_median_growth(combined, codes=codes, min_funds=3)
        bench_label = "Grup medyanı"
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
                  f"Risksiz Faiz (Benchmark): %{risk_free_rate:.1f}{dflt('risk_free_rate') if risk_free_rate == mac.risk_free_rate else ''}<br/>"
                  f"Enflasyon (TÜFE): %{mac.inflation_rate:.0f}{dflt('inflation_rate')} &nbsp;|&nbsp; "
                  f"Politika Faizi: %{mac.policy_rate:.0f}{dflt('policy_rate')}", styles["CoverInfo"]),
        Spacer(1, 10 * mm),
        Paragraph("Bu rapor kantitatif modellere dayanır ve yatırım tavsiyesi değildir. "
                  "Fonlar 'olduğu gibi' kıyaslanır; aktiflik/uygunluk filtresi uygulanmaz — "
                  "rf karşılaştırması bilgilendirici bir bayraktır.", styles["Disclaimer"]),
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
    g = _chart_cmp_growth(combined, codes, chart_dir / "cmp_growth.png",
                          benchmark=bench, benchmark_label=bench_label)
    if g:
        story += [Image(g, width=236 * mm, height=84 * mm), Spacer(1, 3 * mm)]
    pr = _chart_cmp_periods(met, chart_dir / "cmp_periods.png")
    if pr:
        story.append(Image(pr, width=236 * mm, height=76 * mm))
    story.append(PageBreak())

    # 4b) Aylık getiri takvimi + yuvarlanan metrikler (ana raporla aynı içerik)
    hm = _chart_monthly_heatmap(combined, codes, chart_dir / "cmp_monthly_hm.png",
                                median_label="Grup medyanı")
    roll = _chart_rolling(combined, codes, chart_dir / "cmp_rolling.png",
                          rf=risk_free_rate, color_map=color_map)
    if hm:
        n_hm_rows = len(codes) + 1
        hm_h = min((0.42 * n_hm_rows + 1.15) / 9.8 * 236, 150)
        story += [Paragraph("AYLIK GETİRİ TAKVİMİ", styles["Section"]),
                  Paragraph("Karşılaştırılan fonların ay-ay getirisi ve grubun ay medyanı (son satır). Yeşil pozitif, "
                            "kırmızı negatif ayları gösterir; gri hücrelerde fonun o ay verisi yoktur. Tutarlı fonlar "
                            "satır boyunca kesintisiz yeşil ton bırakır.", styles["BodySm"]),
                  Image(hm, width=236 * mm, height=hm_h * mm), PageBreak()]
    if roll:
        story += [Paragraph("YUVARLANAN 63 GÜNLÜK GETİRİ & VOLATİLİTE", styles["Section"]),
                  Paragraph("Üst panel: 63 işlem günlük pencereden yıllıklandırılmış getiri — kesikli gri çizgi risksiz faiz. "
                            "Alt panel: aynı pencerede yıllıklandırılmış volatilite. Performansın döneme mi yayıldığını "
                            "yoksa tek bir sıçramadan mı geldiğini ve risk rejimindeki değişimleri gösterir.", styles["BodySm"]),
                  Image(roll, width=226 * mm, height=118 * mm), PageBreak()]

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
                  "aktiflik/uygunluk filtresi uygulanmaz — 'rf Üzeri Getiri' satırı bilgilendirici bir bayraktır. "
                  f"Büyüme grafiğindeki kesikli gri çizgi {bench_label.lower()} patikasıdır (fonların günlük getiri "
                  "medyanından bileşiklenir, baz=100). Yuvarlanan 63 günlük getiri log-getirilerden yıllıklandırılır; "
                  "aylık takvim ay sonu fiyatlarından hesaplanır.", styles["Body"]),
        Paragraph("UYARI: Bu rapor geçmiş TEFAS verisine dayanır; yatırım tavsiyesi değildir. Geçmiş performans geleceği "
                  "garanti etmez. İşlem maliyetleri ve vergi etkileri modellenmemiştir.", styles["Disclaimer"]),
    ]

    doc = _OutlineDoc(str(out_path), pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=12 * mm,
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

    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    finally:
        shutil.rmtree(chart_dir, ignore_errors=True)

    print(f"[OK] Karşılaştırma raporu: {out_path}")
    return out_path

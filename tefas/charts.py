"""
Matplotlib grafik üreticileri + saf veri-hazırlık (prep) fonksiyonları.

report.py'den ayrıldı (High-value refactor): PDF yerleşimi report.py'de kalır,
grafik ÇİZİMİ burada, grafiğin VERİSİ ise `prep_*` saf fonksiyonlarında yaşar.
Böylece dashboard aynı prep çıktısını Plotly ile çizebilir; PDF ile web aynı
sayıları gösterir.

Performans: `price_pivot(combined)` bir kez kurulur ve pivot gerektiren
üreticilere parametre olarak geçirilir (önceden her üretici ~700k satırlık
frame'i yeniden pivotluyordu). `pivot=None` verilirse üretici kendisi kurar
(geriye uyum + tekil kullanım).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from adjustText import adjust_text
except ImportError:
    adjust_text = None

from . import config, portfolio as pf
from .themes import fund_theme

MPL_NAVY, MPL_BLUE, MPL_GREEN, MPL_GREY = "#13294b", "#1f5fb0", "#0f8a6a", "#b8c1cf"
# Fon-başına tutarlı renkler: bir fon TÜM grafiklerde aynı rengi taşır
# (ana rapor + karşılaştırma). Sıra sabittir, asla döngülenmez; palet
# CVD/kontrast kontrollerinden geçirilmiştir (gri okunan #5d6d7e ve düşük
# kontrastlı #e0a526 değiştirildi, zayıf komşu çiftler ayrıştırıldı).
FUND_PALETTE = ["#1f5fb0", "#bf8410", "#0f8a6a", "#c0392b", "#7d4fb0",
                "#16a085", "#b83a68", "#2e86c1", "#c0622d", "#8e44ad"]


def _chart(fig, path):
    # 300 dpi: PDF'te grafikler sayfa genişliğine (~236 mm) ölçeklendiği için
    # 150 dpi ekranda/yakınlaştırmada bulanık kalıyordu; baskı kalitesi 300.
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


# ─── Saf veri hazırlığı (PDF ve dashboard ortak) ─────────────────────────────

def price_pivot(combined: pd.DataFrame) -> pd.DataFrame:
    """Tarih × Fon Kodu fiyat pivotu (datetime index, tarih sıralı).

    ETL (tarih, fon) çiftini zaten teke indirger; aggfunc yalnızca güvencedir.
    """
    piv = combined.pivot_table(index="Tarih", columns="Fon Kodu",
                               values="Fiyat", aggfunc="last").sort_index()
    piv.index = pd.to_datetime(piv.index)
    return piv


def prep_growth(pivot: pd.DataFrame, codes: list[str]) -> pd.DataFrame | None:
    """Ortak dönemde baz-100 normalize büyüme; veri yetersizse None."""
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return None
    df = pivot[avail].dropna(how="any")
    if len(df) < 10:
        return None
    return (df / df.iloc[0]) * 100

def prep_drawdown(prices: pd.Series) -> tuple[np.ndarray, np.ndarray] | None:
    """Fiyat serisinden (baz-100 patika, zirveye-göre-% drawdown) çifti."""
    p = pd.to_numeric(prices, errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(p) & (p > 0)
    p = p[mask]
    if len(p) < 10:
        return None
    norm = p / p[0] * 100.0
    peak = np.maximum.accumulate(norm)
    dd = (peak - norm) / peak * 100.0
    return norm, dd


def prep_monthly_returns(pivot: pd.DataFrame) -> pd.DataFrame:
    """Ay sonu fiyatlarından aylık getiri (%) — satır: ay (Period), sütun: fon."""
    month_last = pivot.groupby(pivot.index.to_period("M")).last()
    return month_last.pct_change().iloc[1:] * 100.0


def prep_rolling(pivot: pd.DataFrame, codes: list[str],
                 window: int = 63) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Yuvarlanan yıllıklandırılmış getiri ve volatilite (%, günlük ızgara)."""
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return None
    px = pivot[avail]
    logret = np.log(px).diff()
    if logret.dropna(how="all").shape[0] < window + 5:
        return None
    td = config.TRADING_DAYS_PER_YEAR
    roll_ret = (np.exp(logret.rolling(window).sum() * (td / window)) - 1.0) * 100.0
    roll_vol = px.pct_change().rolling(window).std() * np.sqrt(td) * 100.0
    return roll_ret, roll_vol


# ─── Ana rapor grafikleri ────────────────────────────────────────────────────

def chart_top_returns(df, path, n=12):
    d = df.nlargest(n, "Overall_Score").dropna(subset=["Yillik_Getiri"]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9.6, 4.2))
    bars = ax.barh(d["Fon Kodu"], d["Yillik_Getiri"], color=MPL_BLUE, alpha=0.9)
    ax.bar_label(bars, labels=[f"%{v:.0f}" for v in d["Yillik_Getiri"]], fontsize=7.5, padding=3, color=MPL_NAVY)
    ax.set_xlabel("Yıllık Getiri (%)", fontsize=9, color=MPL_NAVY)
    ax.set_title("En İyi Fonlar — Yıllık Getiri", fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.25, linestyle="--")
    ax.margins(x=0.12)
    return _chart(fig, path)


def chart_allocation(portfolio, path):
    labels = [f"{p['Fon Kodu']}\n%{p['Agirlik']:.0f}" for p in portfolio]
    sizes = [p["Agirlik"] for p in portfolio]
    palette = ["#13294b", "#1f5fb0", "#2e86c1", "#0f8a6a", "#37a86b", "#e0a526", "#c0622d", "#7d4fb0", "#5d6d7e"]
    fig, ax = plt.subplots(figsize=(5.2, 4.2))
    wedges, _ = ax.pie(sizes, colors=(palette * 3)[: len(sizes)], startangle=90,
                       wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5))
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8, frameon=False)
    ax.set_title("Önerilen Portföy Dağılımı", fontsize=11, color=MPL_NAVY, fontweight="bold")
    return _chart(fig, path)


def chart_risk_return(df, highlight_codes, path):
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


def chart_growth_history(combined, codes, path, color_map=None, benchmark=None,
                         benchmark_label="Evren medyanı",
                         title="Öne Çıkan Fonların Kümülatif Büyümesi",
                         pivot=None):
    """Öne çıkan fonların ortak dönemde büyümesi. `color_map` fon→renk eşlemesi
    (tear-sheet/detay sayfalarıyla tutarlı); `benchmark` baz-100 akran patikası."""
    if combined is None or not codes:
        return None
    piv = pivot if pivot is not None else price_pivot(combined)
    df_normalized = prep_growth(piv, codes)
    if df_normalized is None:
        return None
    avail = list(df_normalized.columns)
    fig, ax = plt.subplots(figsize=(9.6, 4.5))
    for i, c in enumerate(avail):
        color = (color_map or {}).get(c, FUND_PALETTE[i % len(FUND_PALETTE)])
        ax.plot(df_normalized.index, df_normalized[c], label=c, linewidth=1.6, color=color)
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index)
        b = b[(b.index >= df_normalized.index[0]) & (b.index <= df_normalized.index[-1])]
        if len(b) >= 2:
            b = b / b.iloc[0] * 100.0   # grafiğin kendi dönemine yeniden bazla
            ax.plot(b.index, b.values, label=benchmark_label, linewidth=1.4,
                    color=MPL_GREY, linestyle="--", zorder=1)
    ax.set_ylabel("Sermaye (Başlangıç = 100 TL)", fontsize=9, color=MPL_NAVY)
    ax.set_title(title, fontsize=11, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, alpha=0.25, linestyle="--")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, fontsize=8)
    ax.legend(fontsize=8, loc="upper left", framealpha=0.9)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    return _chart(fig, path)


def chart_correlation_heatmap(combined, codes, path):
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


def chart_distribution(df, top_codes, rf, path):
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


def chart_benchmark_bars(df, rf, path):
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


def chart_sparkline(combined, code, path):
    """Tek fon için kompakt tear-sheet grafiği: büyüme (üst) + sualtı/drawdown (alt)."""
    if combined is None:
        return None
    sub = combined[combined["Fon Kodu"] == code]
    if len(sub) < 10:
        return None
    sub = sub.sort_values("Tarih")
    prices = pd.to_numeric(sub["Fiyat"], errors="coerce")
    t = pd.to_datetime(sub["Tarih"])
    mask = prices.notna() & (prices > 0)
    prepped = prep_drawdown(prices[mask])
    if prepped is None:
        return None
    norm, dd = prepped
    t = t[mask]
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


def chart_risk_contribution(risk, portfolio, path):
    """Fon başına ağırlık vs. gerçek risk katkısı (kovaryanstan)."""
    rc = risk.get("risk_contributions") or {}
    wts = risk.get("weights") or {}
    if not rc:
        return None
    codes = list(rc.keys())
    y = np.arange(len(codes))
    w_pct = [wts.get(c, 0) * 100 for c in codes]
    r_pct = [rc.get(c, 0) * 100 for c in codes]
    fig, ax = plt.subplots(figsize=(9.6, max(4.0, 0.72 * len(codes) + 1.4)))
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


def chart_portfolio_underwater(combined, portfolio, path):
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


def chart_category_mix(df, path, n=10):
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


def chart_monthly_heatmap(combined, codes, path, median_row=True,
                          median_label="Evren medyanı", pivot=None):
    """Aylık getiri takvimi: fonlar × aylar ısı haritası (+ medyan satırı).

    Medyan satırı, verilen `combined` içindeki TÜM fonların ay medyanıdır —
    ana raporda evren, karşılaştırmada grup medyanı (etiket `median_label`).
    Iraksak (diverging) palet, 0 merkezli; NaN hücreler (fon o ay yoktu) açık gri.
    """
    if combined is None or not codes:
        return None
    import matplotlib.colors as mcolors
    piv = pivot if pivot is not None else price_pivot(combined)
    avail = [c for c in codes if c in piv.columns]
    if not avail:
        return None
    monthly = prep_monthly_returns(piv)
    if monthly.empty or len(monthly) < 2:
        return None
    data = monthly[avail].T
    row_labels = list(avail)
    if median_row:
        med = monthly.median(axis=1)          # çerçevedeki tüm fonların ay medyanı
        data = pd.concat([data, med.to_frame(median_label).T])
        row_labels.append(median_label)
    vals = data.to_numpy(dtype=float)
    if not np.isfinite(vals).any():
        return None
    # TwoSlopeNorm vmin < 0 < vmax ister; tüm aylar pozitifken (yüksek enflasyon
    # ortamında olağan) çökmemesi için uçlar 0'ın iki yanına zorlanır.
    vmin = min(np.nanmin(vals), -0.1)
    vmax = max(np.nanmax(vals), 0.1)
    norm = mcolors.TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)
    cmap = plt.get_cmap("RdYlGn").with_extremes(bad="#e8ebef")
    masked = np.ma.masked_invalid(vals)
    fig, ax = plt.subplots(figsize=(9.8, 0.42 * len(row_labels) + 1.15))
    ax.imshow(masked, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(np.arange(len(monthly.index)))
    ax.set_xticklabels([str(p) for p in monthly.index], rotation=90, fontsize=6.5)
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=7.5)
    if median_row:
        ax.get_yticklabels()[-1].set_fontweight("bold")
    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]):
            v = vals[i, j]
            if not np.isfinite(v):
                continue
            r, g, b, _ = cmap(norm(v))
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=6,
                    color="white" if lum < 0.45 else "#1f2733")
    ax.set_title("Aylık Getiri Takvimi (%)", fontsize=11, color=MPL_NAVY, fontweight="bold", pad=10)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.tight_layout()
    return _chart(fig, path)


def chart_rolling(combined, codes, path, rf=None, color_map=None, window=63, pivot=None):
    """Yuvarlanan pencere metrikleri: 63 günlük yıllıklandırılmış getiri (üst)
    ve yıllıklandırılmış volatilite (alt). Fon renkleri color_map ile tutarlı."""
    if combined is None or not codes:
        return None
    piv = pivot if pivot is not None else price_pivot(combined)
    prepped = prep_rolling(piv, codes, window)
    if prepped is None:
        return None
    roll_ret, roll_vol = prepped
    avail = list(roll_ret.columns)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9.6, 5.0), sharex=True, height_ratios=[1.25, 1])
    for i, c in enumerate(avail):
        color = (color_map or {}).get(c, FUND_PALETTE[i % len(FUND_PALETTE)])
        a1.plot(roll_ret.index, roll_ret[c], label=c, linewidth=1.4, color=color)
        a2.plot(roll_vol.index, roll_vol[c], linewidth=1.4, color=color)
    if rf is not None and rf > 0:
        a1.axhline(rf, color=MPL_GREY, linestyle="--", linewidth=1.1, label=f"rf %{rf:.0f}")
    # Aşırı oynak bir fonun kısa-pencere yıllıklandırması (ör. %15.000) ekseni
    # ezip diğer fonları düz çizgiye çevirmesin: getiri ekseni makul banda kırpılır.
    finite = roll_ret.to_numpy(dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size:
        hi_cap = max(300.0, (rf or 0.0) * 3.0)
        lo_cap = -100.0
        hi, lo = float(finite.max()), float(finite.min())
        if hi > hi_cap or lo < lo_cap:
            a1.set_ylim(max(lo, lo_cap) - 10, min(hi, hi_cap))
            a1.text(0.995, 0.96, "getiri ekseni kırpıldı", transform=a1.transAxes,
                    ha="right", va="top", fontsize=6.5, color=MPL_GREY)
    a1.set_ylabel(f"{window}g getiri (yıllık, %)", fontsize=8, color=MPL_NAVY)
    a1.set_title(f"Yuvarlanan {window} Günlük Getiri ve Volatilite (yıllıklandırılmış)",
                 fontsize=11, color=MPL_NAVY, fontweight="bold")
    a1.legend(fontsize=7.5, ncol=min(len(avail) + 1, 6), framealpha=0.9, loc="upper left")
    a2.set_ylabel(f"{window}g volatilite (%)", fontsize=8, color=MPL_NAVY)
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


def chart_fund_detail(combined, code, path, color=None, benchmark=None,
                      benchmark_label="Tema medyanı"):
    """Tek fonun büyük detay grafiği: büyüme + akran medyanı (üst), sualtı (alt)."""
    if combined is None:
        return None
    sub = combined[combined["Fon Kodu"] == code].sort_values("Tarih")
    if len(sub) < 10:
        return None
    prices = pd.to_numeric(sub["Fiyat"], errors="coerce")
    t = pd.to_datetime(sub["Tarih"])
    mask = prices.notna() & (prices > 0)
    prepped = prep_drawdown(prices[mask])
    if prepped is None:
        return None
    norm_, dd = prepped
    t = t[mask].reset_index(drop=True)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.4, 3.4), height_ratios=[2.2, 1], sharex=True)
    a1.plot(t, norm_, color=color or MPL_NAVY, linewidth=1.6, label=code)
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index)
        b = b[(b.index >= t.min()) & (b.index <= t.max())]
        if len(b) >= 2:
            b = b / b.iloc[0] * 100.0
            a1.plot(b.index, b.values, color=MPL_GREY, linestyle="--", linewidth=1.2,
                    label=benchmark_label, zorder=1)
    a1.axhline(100, color=MPL_GREY, linewidth=0.6, linestyle=":")
    a1.set_ylabel("Değer (100 taban)", fontsize=8, color=MPL_NAVY)
    a1.legend(fontsize=7.5, framealpha=0.9, loc="upper left")
    a2.fill_between(t, 0, dd, color="#c0392b", alpha=0.35, linewidth=0)
    a2.plot(t, dd, color="#c0392b", linewidth=0.8)
    a2.invert_yaxis()
    a2.set_ylabel("DD (%)", fontsize=8, color=MPL_NAVY)
    import matplotlib.dates as mdates
    a2.xaxis.set_major_locator(mdates.AutoDateLocator())
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for ax in (a1, a2):
        ax.grid(True, alpha=0.2, linestyle="--")
        ax.tick_params(labelsize=7)
        for sp in ax.spines.values():
            sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


def chart_monthly_bars(combined, code, path):
    """Tek fonun aylık getirileri: pozitif yeşil, negatif kırmızı bar."""
    if combined is None:
        return None
    sub = combined[combined["Fon Kodu"] == code].sort_values("Tarih")
    if len(sub) < 25:
        return None
    p = pd.to_numeric(sub["Fiyat"], errors="coerce")
    t = pd.to_datetime(sub["Tarih"])
    s = pd.Series(p.to_numpy(), index=t)
    month_last = s.groupby(s.index.to_period("M")).last()
    monthly = month_last.pct_change().dropna() * 100.0
    if len(monthly) < 2:
        return None
    colors_ = [MPL_GREEN if v >= 0 else "#c0392b" for v in monthly]
    fig, ax = plt.subplots(figsize=(4.0, 3.4))
    bars = ax.bar(np.arange(len(monthly)), monthly.to_numpy(), color=colors_, alpha=0.9)
    ax.bar_label(bars, labels=[f"{v:.1f}" for v in monthly], fontsize=5.5, padding=1.5, color=MPL_NAVY)
    ax.axhline(0, color=MPL_GREY, linewidth=0.7)
    ax.set_xticks(np.arange(len(monthly)))
    ax.set_xticklabels([str(pp) for pp in monthly.index], rotation=90, fontsize=6)
    ax.set_ylabel("Aylık getiri (%)", fontsize=8, color=MPL_NAVY)
    ax.set_title("Aylık Getiriler", fontsize=10, color=MPL_NAVY, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.2, linestyle="--")
    ax.margins(y=0.15)
    ax.tick_params(labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#d4dbe6")
    fig.tight_layout()
    return _chart(fig, path)


# ─── Karşılaştırma modu grafikleri ───────────────────────────────────────────

def fund_color(codes, code):
    return FUND_PALETTE[codes.index(code) % len(FUND_PALETTE)] if code in codes else MPL_GREY


def cmp_pivot(combined, codes):
    pivot = price_pivot(combined)
    avail = [c for c in codes if c in pivot.columns]
    if not avail:
        return None, []
    return pivot[avail], avail


def chart_cmp_growth(combined, codes, path, benchmark=None, benchmark_label="Evren medyanı"):
    """Karşılaştırılan fonların ortak dönemde normalize (100 taban) büyümesi.
    `benchmark`: baz-100 akran medyan patikası — grafiğin dönemine yeniden bazlanır."""
    pivot, avail = cmp_pivot(combined, codes)
    if pivot is None:
        return None
    norm = prep_growth(pivot, avail)
    if norm is None:
        return None
    fig, ax = plt.subplots(figsize=(9.6, 3.7))
    for c in avail:
        ax.plot(norm.index, norm[c], label=c, linewidth=1.7, color=fund_color(codes, c))
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index)
        b = b[(b.index >= norm.index[0]) & (b.index <= norm.index[-1])]
        if len(b) >= 2:
            b = b / b.iloc[0] * 100.0
            ax.plot(b.index, b.values, label=benchmark_label, linewidth=1.4,
                    color=MPL_GREY, linestyle="--", zorder=1)
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


def chart_cmp_periods(met, path):
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


def chart_cmp_scatter(met, path):
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


def chart_cmp_drawdown(combined, codes, path):
    """Her fonun sualtı (drawdown) eğrisi tek eksende — dayanıklılık kıyası."""
    pivot, avail = cmp_pivot(combined, codes)
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
        ax.plot(s.index, dd, label=c, linewidth=1.3, color=fund_color(codes, c))
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


RADAR_AXES = [("Yıllık Getiri", "Yillik_Getiri", "high"), ("Sharpe", "Sharpe_Orani", "high"),
              ("Sortino", "Sortino_Orani", "high"), ("Düşük Vol.", "Yillik_Volatilite", "low"),
              ("Düşük DD", "Max_Drawdown", "low"), ("Poz. Gün", "Pozitif_Gun_Orani", "high")]


def chart_cmp_radar(met, path):
    """Çok-boyutlu göreli karşılaştırma (fonlar arası min-maks normalize spider)."""
    labels = [a[0] for a in RADAR_AXES]
    norm = []
    for _, col, direction in RADAR_AXES:
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

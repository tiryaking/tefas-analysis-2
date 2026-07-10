"""Fon Detay: tek fonun künyesi, gerekçesi, akran kıyası, büyüme/drawdown/
rolling grafikleri ve skor geçmişi.

Grafik verileri PDF ile AYNI `charts.prep_*` fonksiyonlarından gelir — web ile
rapor aynı sayıları gösterir; yalnızca çizici farklı (Plotly ↔ matplotlib).
"""
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

from tefas import charts, config, narrative, tefas_web, themes
from tefas.dashboard import data, figures, ui

ft = data.sidebar_fund_type()
st.title("Fon Detay")

scored = data.enriched_frame(ft)
combined = data.load_combined(ft)
if scored is None or scored.empty or combined is None:
    data.no_data_warning(ft)
    st.stop()

labels = ui.fund_label_map(scored)
# Bir tablodan tıklanarak gelindiyse o fon ön-seçili olur; yoksa en yüksek skorlu.
preselect = ui.consume_detail_code()
_init_code = preselect if preselect in labels \
    else scored.nlargest(1, "Overall_Score")["Fon Kodu"].iloc[0]
# session_state ile seçim sürdürülebilirlik: butona tıklanınca rerun
# gerçekleştiğinde selectbox'ın seçimi kaybolmaz.
if "detail_code" not in st.session_state:
    st.session_state.detail_code = str(_init_code)
code = st.selectbox("Fon seç", sorted(labels),
                    format_func=lambda c: labels[c],
                    key="detail_code")

row = scored[scored["Fon Kodu"].astype(str) == code].iloc[0]
st.caption(str(row["Fon Adi"]))
st.info("💡 " + narrative.build_rationale(row))

# ── TEFAS Web Entegrasyonu ─────────────────────────────────────────────────
CACHE_KEY = f"tefas_web_{code}"
SHOW_KEY = f"tefas_show_{code}"

web_info = st.session_state.get(CACHE_KEY)

# Buton: veri yoksa çek, varsa göster/gizle
btn_label = "🔍 TEFAS'tan Bilgi Getir"
if web_info is not None:
    showing = st.session_state.get(SHOW_KEY, True)
    btn_label = "🙈 TEFAS Verisini Gizle" if showing else "👁️ TEFAS Verisini Göster"

if st.button(btn_label, key=f"btn_tefas_{code}"):
    if web_info is None:
        # İlk çekim
        fetch_status = st.status(
            f"TEFAS'tan {code} bilgileri çekiliyor...",
            expanded=True,
        )
        new_info = tefas_web.fetch_fund_info(code)
        if new_info is None:
            fetch_status.update(
                label="⚠️ TEFAS'a bağlanılamadı!",
                state="error",
                expanded=False,
            )
            try:
                last_err = tefas_web.get_last_error()
            except AttributeError:
                last_err = "(modül güncel değil — lütfen dashboard'u yeniden başlatın)"
            st.warning(
                "İnternet bağlantınızı kontrol edin veya daha sonra tekrar deneyin. "
                "WAF güvenlik duvarı aşılamadıysa cloudscraper yüklemeyi deneyin: "
                "`pip install cloudscraper`"
            )
            st.caption(f"Hata detayı: {last_err}")
            st.session_state[CACHE_KEY] = None
        else:
            fetch_status.update(
                label=f"✅ {code} bilgileri TEFAS'tan getirildi",
                state="complete",
                expanded=False,
            )
            st.session_state[CACHE_KEY] = new_info
            st.session_state[SHOW_KEY] = True
            st.rerun()
    else:
        # Toggle göster/gizle
        current = st.session_state.get(SHOW_KEY, True)
        st.session_state[SHOW_KEY] = not current
        st.rerun()

web_info = st.session_state.get(CACHE_KEY)
showing = st.session_state.get(SHOW_KEY, True)
if web_info and showing:
    with st.container(border=True):
        st.markdown(
            f"""<div style="margin-bottom:4px">
                <span style="font-size:1.05rem;font-weight:600">📡 TEFAS Canlı Veri — {code}</span>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Özel metric helper'ı ──────────────────────────────────────────────
        def _metric_card(label: str, value: str, color: str = "#1a1a2e") -> str:
            return (
                f'<div style="background:#f8f9fb;border-radius:8px;padding:8px 12px;'
                f'min-width:0;text-align:center">'
                f'<div style="font-size:0.65rem;color:#6b7280;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis">{label}</div>'
                f'<div style="font-size:1.05rem;font-weight:700;color:{color};'
                f'margin-top:2px;white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis">{value}</div>'
                f'</div>'
            )

        def _section_label(text: str) -> str:
            return (
                f'<div style="font-size:0.7rem;font-weight:600;color:#6b7280;'
                f'text-transform:uppercase;letter-spacing:0.5px;margin:10px 0 4px">'
                f'{text}</div>'
            )

        # ── Kimlik Bilgileri ──────────────────────────────────────────────────
        st.markdown(_section_label("Kimlik Bilgileri"), unsafe_allow_html=True)
        pdurum = web_info.get("platform_durumu", "-")
        pdurum_norm = pdurum.replace("İ", "i").replace("ı", "i").lower()
        if "işlem görüyor" in pdurum_norm and "görmüyor" not in pdurum_norm:
            pdurum_html = "✅ " + pdurum
            pdurum_clr = "#0f8a6a"
        elif "görmüyor" in pdurum_norm:
            pdurum_html = "❌ " + pdurum
            pdurum_clr = "#c0392b"
        else:
            pdurum_html = pdurum
            pdurum_clr = "#1a1a2e"

        khtml = (
            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">'
            + _metric_card("ISIN Kodu", web_info.get("isin_kodu", "-"))
            + _metric_card("Platform Durumu", pdurum_html, pdurum_clr)
            + _metric_card("Risk Değeri", web_info.get("risk_degeri", "-"))
            + _metric_card("Kategorisi", web_info.get("kategorisi", "-"))
            + '</div>'
        )
        st.markdown(khtml, unsafe_allow_html=True)

        # ── İşlem Bilgileri ───────────────────────────────────────────────────
        st.markdown(_section_label("İşlem Bilgileri"), unsafe_allow_html=True)
        ihtml = (
            '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px">'
            + _metric_card("Alış Valörü", web_info.get("alis_valoru", "-"))
            + _metric_card("Satış Valörü", web_info.get("satis_valoru", "-"))
            + _metric_card("Giriş Komisyonu", web_info.get("giris_komisyonu", "-"))
            + _metric_card("Çıkış Komisyonu", web_info.get("cikis_komisyonu", "-"))
            + _metric_card("Kategori Derecesi", web_info.get("kategori_derecesi", "-"))
            + '</div>'
            '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:6px">'
            + _metric_card("İşlem Başlama", web_info.get("is_baslama_saati", "-"))
            + _metric_card("Son İşlem", web_info.get("son_is_saati", "-"))
            + _metric_card("Min Alış", web_info.get("min_alis", "-"))
            + _metric_card("Min Satış", web_info.get("min_satis", "-"))
            + '<div></div>'
            + '</div>'
        )
        st.markdown(ihtml, unsafe_allow_html=True)

        # ── Fon İstatistikleri ────────────────────────────────────────────────
        st.markdown(_section_label("Fon İstatistikleri"), unsafe_allow_html=True)
        fhtml = (
            '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px">'
            + _metric_card("Son Fiyat (TL)", web_info.get("son_fiyat", "-"))
            + _metric_card("Günlük Getiri", web_info.get("gunluk_getiri", "-"))
            + _metric_card("Pay Adedi", web_info.get("pay_adedi", "-"))
            + _metric_card("Yatırımcı Sayısı", web_info.get("yatirimci_sayisi", "-"))
            + _metric_card("Pazar Payı", web_info.get("pazar_payi", "-"))
            + '</div>'
        )
        st.markdown(fhtml, unsafe_allow_html=True)

        # ── Getiri Bilgisi ───────────────────────────────────────────────────
        st.markdown(_section_label("Getiri Bilgisi"), unsafe_allow_html=True)
        ghtml = (
            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">'
            + _metric_card("Son 1 Ay", web_info.get("getiri_1ay", "-"))
            + _metric_card("Son 3 Ay", web_info.get("getiri_3ay", "-"))
            + _metric_card("Son 6 Ay", web_info.get("getiri_6ay", "-"))
            + _metric_card("Son 1 Yıl", web_info.get("getiri_1yil", "-"))
            + '</div>'
        )
        st.markdown(ghtml, unsafe_allow_html=True)

        # ── Varlık Dağılımı (tek grafik, oranlar barlarda) ───────────────────
        varlik = web_info.get("varlik_dagilimi", [])
        if varlik:
            st.markdown(_section_label("Varlık Dağılımı"), unsafe_allow_html=True)
            vdf = pd.DataFrame(varlik)
            try:
                vdf["Oran_num"] = pd.to_numeric(
                    vdf["Oran"].str.replace("%", "").str.replace(",", "."),
                    errors="coerce",
                )
                vdf = vdf.dropna(subset=["Oran_num"]).sort_values("Oran_num")

                fig_v = go.Figure()
                fig_v.add_trace(go.Bar(
                    y=vdf["Varlık Türü"],
                    x=vdf["Oran_num"],
                    orientation="h",
                    marker=dict(
                        color=vdf["Oran_num"],
                        colorscale=[[0, "#dbeafe"], [0.4, "#93c5fd"], [1, "#1e3a5f"]],
                    ),
                    text=vdf["Oran"],
                    textposition="outside",
                    textfont=dict(size=11, color="#374151"),
                    hovertemplate="<b>%{y}</b><br>%{x:.2f}%<extra></extra>",
                ))
                fig_v.update_layout(
                    height=max(180, 28 * len(vdf) + 30),
                    width=680,
                    margin=dict(t=6, b=6, l=6, r=60),
                    xaxis=dict(title="", showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(title="", automargin=True, tickfont=dict(size=11)),
                    showlegend=False,
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_v, use_container_width=False, config={"displayModeBar": False})
            except Exception:
                st.dataframe(vdf, use_container_width=True, hide_index=True)

        # ── KAP + Ham Veri (aynı satır) ──────────────────────────────────────
        kap_url = web_info.get("kap_url")
        bottom_cols = st.columns([1, 1])
        with bottom_cols[0]:
            if kap_url:
                st.link_button("🔗 KAP Sayfasını Aç", kap_url, use_container_width=True)
        with bottom_cols[1]:
            with st.expander("Ham TEFAS Verisi"):
                st.json(web_info)

# ── Tear-sheet metrik kartları ────────────────────────────────────────────────
num = lambda c: pd.to_numeric(pd.Series([row.get(c)]), errors="coerce").iloc[0]
r1 = st.columns(6)
r1[0].metric("Composite skor", narrative.fmt(num("Overall_Score"), 1))
r1[1].metric("Yıllık getiri", narrative.pct(num("Yillik_Getiri")))
r1[2].metric("Volatilite", narrative.pct(num("Yillik_Volatilite")))
r1[3].metric("Sharpe", narrative.fmt(num("Sharpe_Orani"), 2))
r1[4].metric("Sortino", narrative.fmt(num("Sortino_Orani"), 2))
r1[5].markdown(
    f'<div style="background:transparent;padding:0">'
    f'<div style="font-size:0.68rem;color:#6b7280">Tema</div>'
    f'<div style="font-size:0.95rem;font-weight:600;color:#1a1a2e;'
    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px">'
    f'{str(row.get("Tema", "-"))}</div></div>',
    unsafe_allow_html=True,
)
r2 = st.columns(6)
r2[0].metric("Max drawdown", narrative.pct(num("Max_Drawdown")))
r2[1].metric("Calmar", narrative.fmt(num("Calmar_Orani"), 2))
r2[2].metric("VaR %95", narrative.pct(num("VaR_95")))
r2[3].metric("CVaR %95", narrative.pct(num("CVaR_95")))
r2[4].metric("Reel getiri", narrative.pct(num("Reel_Getiri_1Y")))
r2[5].metric("AUM (mn TL)", narrative.fmt(num("Fon_Toplam_Deger_Milyon_TL"), 0))

# ── Tarih aralığı (grafik verilerini dilimler) ────────────────────────────────
sub = combined[combined["Fon Kodu"].astype(str) == code].sort_values("Tarih").copy()
sub["Tarih"] = pd.to_datetime(sub["Tarih"])
rng = None
if len(sub) > 2:
    lo, hi = sub["Tarih"].min().to_pydatetime(), sub["Tarih"].max().to_pydatetime()
    if lo < hi:
        rng = st.slider("Tarih aralığı", min_value=lo, max_value=hi, value=(lo, hi),
                        format="YYYY-MM-DD", key="detay_range")
if rng:
    sub = sub[(sub["Tarih"] >= pd.Timestamp(rng[0])) & (sub["Tarih"] <= pd.Timestamp(rng[1]))]

prices = pd.to_numeric(sub["Fiyat"], errors="coerce")
mask = prices.notna() & (prices > 0)
prepped = charts.prep_drawdown(prices[mask])
if prepped is None:
    st.info("Seçili aralıkta yeterli fiyat geçmişi yok (<10 gözlem).")
    st.stop()
norm, dd = prepped
tt = pd.to_datetime(sub["Tarih"])[mask]

# ── Büyüme (akran medyanı çizgili) + sualtı ───────────────────────────────────
theme = row.get("Tema")
peers = scored.loc[scored["Tema"] == theme, "Fon Kodu"].astype(str).tolist() \
    if "Tema" in scored.columns and pd.notna(theme) else []
bench, blabel = None, "Evren medyanı"
if len(peers) >= config.THEME_MIN_FUNDS:
    bench = themes.theme_median_growth(combined, codes=peers)
    blabel = f"Tema medyanı ({len(peers)} fon)"
else:
    bench = themes.theme_median_growth(combined)

norm_df = pd.DataFrame({code: norm}, index=tt)
c_left, c_right = st.columns(2)
c_left.plotly_chart(figures.fig_growth(norm_df, benchmark=bench, benchmark_label=blabel,
                                       title="Kümülatif Büyüme (baz=100)"), width="stretch")
fig_dd = go.Figure()
fig_dd.add_scatter(x=tt, y=-dd, mode="lines", fill="tozeroy", name="Drawdown",
                   line=dict(color="#c0392b", width=1))
# Sıfır referansını her zaman göster: sığ drawdown'lu fonlarda otomatik eksen
# 0'ı kesip grafiği "asılı" gösteriyordu.
fig_dd.update_yaxes(rangemode="tozero")

# ── Drawdown süre etiketleri ──────────────────────────────────────────────
dd_series = pd.Series(dd, index=tt)
in_dd = dd_series > 0
groups = (in_dd != in_dd.shift()).cumsum()
dd_periods = []
for gid, grp in dd_series[in_dd].groupby(groups[in_dd]):
    if (grp.index[-1] - grp.index[0]).days < 3:
        continue
    trough_idx = grp.idxmax()
    trough_val = grp.max()
    start = grp.index[0]
    end = grp.index[-1]
    duration = (end - start).days
    dd_periods.append({
        "start": start, "end": end, "trough": trough_idx,
        "depth": trough_val, "duration": duration,
    })

if dd_periods:
    max_depth = max(p["depth"] for p in dd_periods)
    for p in dd_periods:
        mid = p["trough"]
        depth = p["depth"]
        dur = p["duration"]
        label = f"{dur} gün"
        y_offset = -depth * 0.15 if depth > 0 else -0.3
        fig_dd.add_annotation(
            x=mid, y=-(depth + y_offset),
            text=f"<b>{label}</b>",
            showarrow=True, arrowhead=0, arrowsize=0.8,
            arrowwidth=1, arrowcolor="#7f1d1d",
            font=dict(size=10, color="#7f1d1d"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#7f1d1d",
            borderwidth=0.5, borderpad=2,
        )

fig_dd.update_layout(title="Sualtı / Drawdown (%)", height=380,
                     yaxis_title="Zirveye göre kayıp (%)", margin=dict(t=40, b=10))
c_right.plotly_chart(fig_dd, width="stretch")

# ── Yuvarlanan metrikler + aylık getiriler (paylaşılan prep) ──────────────────
pivot = charts.price_pivot(sub)
rolled = charts.prep_rolling(pivot, [code])
if rolled is not None:
    roll_ret, roll_vol = rolled
    st.plotly_chart(figures.fig_rolling(roll_ret, roll_vol,
                                        rf=config.macro().risk_free_rate), width="stretch")

monthly = charts.prep_monthly_returns(pivot)
if not monthly.empty and code in monthly.columns:
    mr = monthly[code].dropna()
    fig_m = go.Figure()
    fig_m.add_bar(x=[str(p) for p in mr.index], y=mr.values,
                  marker_color=["#0f8a6a" if v >= 0 else "#c0392b" for v in mr.values])
    fig_m.update_layout(title="Aylık Getiriler (%)", height=300, margin=dict(t=40, b=10))
    st.plotly_chart(fig_m, width="stretch")

# ── Akran kıyas tablosu (fon vs tema medyanı vs evren medyanı) ────────────────
peer_cols = [("Yıllık Getiri", "Yillik_Getiri"), ("Volatilite", "Yillik_Volatilite"),
             ("Sharpe", "Sharpe_Orani"), ("Sortino", "Sortino_Orani"),
             ("Max Drawdown", "Max_Drawdown"), ("VaR %95", "VaR_95"),
             ("Reel Getiri", "Reel_Getiri_1Y"), ("AUM (mn TL)", "Fon_Toplam_Deger_Milyon_TL")]
if "Tema" in scored.columns:
    theme_meds = themes.theme_medians(scored, [c for _, c in peer_cols])
    tmed = theme_meds.loc[theme] if (theme_meds is not None and theme in theme_meds.index) else None
    peer_rows = []
    for label, col in peer_cols:
        peer_rows.append({
            "Metrik": label,
            "Fon": narrative.fmt(row.get(col), 2),
            "Tema Medyanı": narrative.fmt(tmed.get(col), 2) if tmed is not None and col in tmed.index else "—",
            "Evren Medyanı": narrative.fmt(pd.to_numeric(scored[col], errors="coerce").median(), 2)
            if col in scored.columns else "—",
        })
    st.subheader("Akran Kıyası")
    st.dataframe(pd.DataFrame(peer_rows), width="stretch", hide_index=True)

# ── Skor geçmişi zaman çizgisi ────────────────────────────────────────────────
hist = data.load_history(ft)
if hist is not None and not hist.empty:
    fh = hist[hist["Fon Kodu"].astype(str) == code].copy()
    n_snap_total = fh["Tarih"].nunique()
    st.subheader("Skor Geçmişi")
    if n_snap_total < 2:
        st.info("Trend için en az 2 anlık kayıt gerekli — her `tefas run` bir kayıt "
                "ekler; henüz yeterli geçmiş birikmedi.")
    else:
        fh["Tarih"] = pd.to_datetime(fh["Tarih"])
        if rng:
            fh = fh[(fh["Tarih"] >= pd.Timestamp(rng[0])) & (fh["Tarih"] <= pd.Timestamp(rng[1]))]
        n_snap = fh["Tarih"].nunique()
        if n_snap == 0:
            st.info("Seçili tarih aralığında skor geçmişi kaydı bulunamadı.")
        else:
            fig_h = px.line(fh.sort_values("Tarih"), x="Tarih",
                            y=["Overall_Score", "Overall_Persentil"], markers=True,
                            labels={"value": "Skor / Persentil (0–100)", "variable": ""})
            # 0–100 sabit eksen: skor/persentil zaten bu ölçekte; otomatik sıkıştırma
            # tepe fonlarda sabit yüksek değeri "boş düz çizgi" gibi göstermesin.
            fig_h.update_yaxes(range=[0, 100])
            fig_h.update_layout(height=320, margin=dict(t=20, b=10),
                                legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig_h, width="stretch")
            st.caption(f"{n_snap} anlık kayıt · Persentil = fonun evren içindeki sıra yüzdeliği "
                       "(100 = en tepe). Tepe fonlarda çizgiler yüksekte ve düz seyreder — bu "
                       "istikrar demektir, veri eksikliği değil.")

with st.expander("Tüm metrikler"):
    st.dataframe(row.to_frame("Değer").astype(str), width="stretch")

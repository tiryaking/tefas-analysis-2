"""Portföyüm: işlem defteri düzenleme + pozisyon/K-Z + XIRR/TWR + değer grafiği.

İşlem defteri `portfolio_transactions.csv` — CLI (`tefas holdings`) ile aynı
dosya, tek doğruluk kaynağı. Kayıt atomiktir (geçici dosya + değiştir) ve
kaydetmeden önce `holdings.load_transactions` doğrulamasından geçer.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefas import config, holdings
from tefas.dashboard import data

st.set_page_config(page_title="Portföyüm", page_icon="💼", layout="wide")
ft = data.sidebar_fund_type()
st.title("Portföyüm")

TXN_PATH = config.DEFAULT_TRANSACTIONS_PATH


def _load_editor_df() -> pd.DataFrame:
    if TXN_PATH.exists():
        raw = pd.read_csv(TXN_PATH, dtype=str, encoding="utf-8-sig")
        raw.columns = [c.strip() for c in raw.columns]
        return raw
    return pd.DataFrame(columns=holdings.TXN_COLUMNS)


def _save_atomic(df: pd.DataFrame) -> None:
    """Önce geçici dosyaya yaz + doğrula, sonra atomik değiştir."""
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=str(TXN_PATH.parent))
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        holdings.load_transactions(Path(tmp))   # doğrulama — hatalıysa raise
        os.replace(tmp, TXN_PATH)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink(missing_ok=True)


st.subheader("İşlem defteri")
st.caption(f"Dosya: `{TXN_PATH.name}` — satır ekleyip silebilirsiniz. "
           "Islem: ALIS veya SATIS; tarih: YYYY-AA-GG.")
edited = st.data_editor(_load_editor_df(), num_rows="dynamic",
                        use_container_width=True, key="txn_editor")
if st.button("Kaydet", type="primary"):
    try:
        _save_atomic(edited.dropna(how="all"))
        st.success("Kaydedildi. CLI (`tefas holdings show`) aynı dosyayı görür.")
        st.rerun()
    except (ValueError, FileNotFoundError) as e:
        st.error(f"Kaydedilmedi — doğrulama hatası:\n\n{e}")

# ── Pozisyonlar & getiri ─────────────────────────────────────────────────────
combined = data.load_combined(ft)
if not TXN_PATH.exists():
    st.info("Henüz işlem defteri yok — yukarıdaki tabloya ilk alımınızı girin ve kaydedin.")
    st.stop()
if combined is None:
    data.no_data_warning(ft)
    st.stop()

try:
    txns = holdings.load_transactions(TXN_PATH)
except (ValueError, FileNotFoundError) as e:
    st.error(str(e))
    st.stop()

pos = holdings.positions(txns)
val = holdings.valuation(pos, combined)
open_pos = val[val["Adet"] > 0]
total_value = float(open_pos["Deger"].sum())
total_cost = float(open_pos["Maliyet"].sum())
as_of = pd.to_datetime(combined["Tarih"]).max()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Toplam değer", f"{total_value:,.0f} TL".replace(",", "."))
k2.metric("Açık K/Z", f"{total_value - total_cost:,.0f} TL".replace(",", "."),
          delta=f"%{(total_value / total_cost - 1) * 100:.1f}" if total_cost > 0 else None)
k3.metric("Realize K/Z", f"{float(val['Realize_KZ'].sum()):,.0f} TL".replace(",", "."))
mwr = holdings.xirr(holdings.xirr_cashflows(txns, total_value, as_of))
k4.metric("XIRR (yıllık)", f"%{mwr * 100:.1f}" if mwr == mwr else "—",
          help="Para-ağırlıklı getiri: 'benim param ne kazandı'")
t = holdings.twr(txns, combined)
k5.metric("TWR", f"%{t['twr'] * 100:.1f}" if t["twr"] == t["twr"] else "—",
          help=f"Zaman-ağırlıklı, {t['gun']} gün — fon/benchmark kıyası için doğru ölçü")

st.subheader("Pozisyonlar")
if open_pos.empty:
    st.info("Açık pozisyon yok.")
else:
    show = open_pos[["Fon Kodu", "Adet", "Ortalama_Maliyet", "Son_Fiyat", "Son_Tarih",
                     "Deger", "Deger_KZ", "Getiri_Pct", "Agirlik", "Realize_KZ", "Veri_Bayat"]].copy()
    show["Agirlik"] = show["Agirlik"] * 100
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={
                     "Getiri_Pct": st.column_config.NumberColumn("Getiri %", format="%.1f"),
                     "Agirlik": st.column_config.NumberColumn("Ağırlık %", format="%.1f"),
                     "Veri_Bayat": st.column_config.CheckboxColumn("Bayat veri?"),
                 })
    stale = open_pos[open_pos["Veri_Bayat"]]
    if not stale.empty:
        st.warning(f"Bayat/eksik NAV: {', '.join(stale['Fon Kodu'])} — değerler güncel olmayabilir.")

series = holdings.portfolio_value_series(txns, combined)
if len(series) >= 2:
    fig = go.Figure()
    fig.add_scatter(x=series.index, y=series["Deger"], mode="lines", name="Portföy değeri",
                    line=dict(width=2))
    flows = series[series["Net_Akis"] != 0]
    fig.add_scatter(x=flows.index, y=flows["Deger"], mode="markers", name="İşlem günü",
                    marker=dict(size=8, symbol="diamond", color="#bf8410"))
    fig.update_layout(title="Portföy Değeri (TL)", height=380, margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

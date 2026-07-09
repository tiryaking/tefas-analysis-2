"""Streamlit'e bağlı küçük UI yardımcıları (indirme butonu, fon seçici, tarih
aralığı). Saf figür/veri mantığı figures.py ve data.py'de; burada yalnızca
`st` gerektiren tekrar eden parçalar."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tefas import config


def download_df(df: pd.DataFrame, filename: str, label: str = "CSV indir",
                key: str | None = None) -> None:
    """DataFrame'i utf-8-sig CSV olarak indirir (Türkçe Excel uyumlu)."""
    if df is None or df.empty:
        return
    csv = df.to_csv(index=False).encode(config.OUTPUT_ENCODING)
    st.download_button(label, csv, file_name=filename, mime="text/csv", key=key)


def fund_label_map(scored: pd.DataFrame) -> dict[str, str]:
    """Kod → 'KOD — Fon Adı' etiketi."""
    return {str(r["Fon Kodu"]): f"{r['Fon Kodu']} — {str(r.get('Fon Adi', ''))[:55]}"
            for _, r in scored.iterrows()}


def fund_multiselect(scored: pd.DataFrame, key: str, default: list[str] | None = None,
                     max_n: int = 8, label: str = "Fonları seç (2–8)") -> list[str]:
    """Kod→ad etiketli çoklu fon seçimi; en fazla `max_n` uyarısı verir."""
    labels = fund_label_map(scored)
    options = sorted(labels)
    default = [c for c in (default or []) if c in labels][:max_n]
    picked = st.multiselect(label, options, default=default,
                            format_func=lambda c: labels.get(c, c), key=key)
    if len(picked) > max_n:
        st.warning(f"En fazla {max_n} fon karşılaştırılır; ilk {max_n} alındı.")
        picked = picked[:max_n]
    return picked


def date_range_slider(pivot: pd.DataFrame, key: str):
    """Pivot'un tarih aralığı için slider; (başlangıç, bitiş) Timestamp döner.
    Pivot boşsa None döner."""
    if pivot is None or pivot.empty:
        return None
    lo = pivot.index.min().to_pydatetime()
    hi = pivot.index.max().to_pydatetime()
    if lo >= hi:
        return None
    return st.slider("Tarih aralığı", min_value=lo, max_value=hi, value=(lo, hi),
                     format="YYYY-MM-DD", key=key)

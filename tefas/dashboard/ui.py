"""Streamlit'e bağlı küçük UI yardımcıları (indirme butonu, fon seçici, tarih
aralığı). Saf figür/veri mantığı figures.py ve data.py'de; burada yalnızca
`st` gerektiren tekrar eden parçalar."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from tefas import config


def metric_column_config() -> dict:
    """Tüm tablolarda tutarlı kolon biçimi (sayı formatı + Fon Adı genişliği).

    Tabloda bulunmayan kolon anahtarları Streamlit tarafından yoksayılır, bu
    yüzden tek sözlük her tabloya uygulanabilir. Sayıların kısa formatlanması ve
    Fon Adı'nın kontrollü genişliği yatay scroll'u ortadan kaldırır.
    """
    N = st.column_config.NumberColumn
    return {
        "Fon Adi": st.column_config.TextColumn("Fon Adı", width="large"),
        "Fon Adı": st.column_config.TextColumn("Fon Adı", width="large"),
        "Karar_Bayraklari": st.column_config.TextColumn("Bayraklar", width="medium"),
        "Overall_Score": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100, format="%.1f"),
        "Yillik_Getiri": N("Yıl. Getiri %", format="%.1f"),
        "Yillik_Volatilite": N("Volatilite %", format="%.1f"),
        "Sharpe_Orani": N("Sharpe", format="%.2f"),
        "Sortino_Orani": N("Sortino", format="%.2f"),
        "Calmar_Orani": N("Calmar", format="%.2f"),
        "Max_Drawdown": N("Max DD %", format="%.1f"),
        "VaR_95": N("VaR %95", format="%.1f"),
        "VaR_99": N("VaR %99", format="%.1f"),
        "CVaR_95": N("CVaR %95", format="%.1f"),
        "En_Kotu_Gun": N("En Kötü Gün %", format="%.1f"),
        "Reel_Getiri_1Y": N("Reel %", format="%.1f"),
        "Agirlik": N("Ağırlık %", format="%.1f"),
        "Fon_Toplam_Deger_Milyon_TL": N("AUM (mn TL)", format="%.0f"),
        "Firsat_Skoru": N("Fırsat", format="%.1f"),
        "Yas_Ay": N("Yaş (ay)", format="%.1f"),
        "Getiri_1A": N("1A %", format="%.1f"),
        "Getiri_3A": N("3A %", format="%.1f"),
        "Veri_Noktasi_Sayisi": N("Veri (gün)", format="%d"),
    }


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

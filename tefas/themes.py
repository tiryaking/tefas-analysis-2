"""
Fon teması sınıflandırması ve tema-bazlı akran (peer) istatistikleri.

`fund_theme` daha önce report.py içindeydi; skorlamanın da temaya ihtiyacı
olduğu için (rapor katmanı reportlab/matplotlib çeker) buraya taşındı.

Akran kıyası tamamen veri-seti içidir (harici endeks yok): bir fonun teması
içindeki medyan/yüzdelik konumu, "kategorisine göre nasıl?" sorusunu yanıtlar.
En az `config.THEME_MIN_FUNDS` fon içermeyen temalar akran istatistiği üretmez.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

THEMES = [
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
    """Fon adından anahtar-kelime eşleşmesiyle tema; eşleşme yoksa 'Diğer'."""
    if pd.isna(name):
        return "Diğer"
    up = str(name).upper()
    for theme, kws in THEMES:
        if any(k in up for k in kws):
            return theme
    return "Diğer"


def add_theme(df: pd.DataFrame, name_col: str = "Fon Adi") -> pd.DataFrame:
    """`Tema` sütununu ekler (varsa üzerine yazar); df'i yerinde değiştirmez."""
    df = df.copy()
    names = df[name_col] if name_col in df.columns else pd.Series(np.nan, index=df.index)
    df["Tema"] = names.map(fund_theme)
    return df


def theme_relative_percentile(df: pd.DataFrame, value_col: str = "Yillik_Getiri",
                              theme_col: str = "Tema",
                              min_funds: int | None = None) -> pd.Series:
    """Fonun kendi teması içindeki yüzdelik konumu (0–100).

    Temada `min_funds`'tan az fon varsa NaN (akran kıyası anlamsız).
    NaN değerli fonlar yüzdelik almaz (NaN kalır).
    """
    if min_funds is None:
        min_funds = config.THEME_MIN_FUNDS
    vals = pd.to_numeric(df[value_col], errors="coerce")
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for _, idx in df.groupby(theme_col).groups.items():
        group_vals = vals.loc[idx]
        if group_vals.notna().sum() < min_funds:
            continue
        out.loc[idx] = group_vals.rank(pct=True) * 100.0
    return out


def theme_medians(df: pd.DataFrame, cols: list[str], theme_col: str = "Tema",
                  min_funds: int | None = None) -> pd.DataFrame:
    """Tema başına medyan metrik tablosu + fon sayısı (`Fon_Sayisi`).

    `min_funds` altındaki temalar tabloya girmez.
    """
    if min_funds is None:
        min_funds = config.THEME_MIN_FUNDS
    present = [c for c in cols if c in df.columns]
    grp = df.groupby(theme_col)
    med = grp[present].median(numeric_only=True)
    med["Fon_Sayisi"] = grp.size()
    return med[med["Fon_Sayisi"] >= min_funds]


def theme_median_growth(combined: pd.DataFrame, codes: list[str] | None = None,
                        min_funds: int = 3) -> pd.Series | None:
    """Akran medyan büyüme patikası (baz=100).

    Her gün için fonların günlük getirilerinin MEDYANI alınır ve bileşiklenir
    ("medyan getiri endeksi"). Fonları başlangıçta 100'e normalleyip fiyat
    medyanı almaktan farklı olarak, geç başlayan fonların seriye sonradan
    katılması patikayı çarpıtmaz. Gün başına `min_funds`'tan az gözlem varsa
    o gün atlanır. Yeterli veri yoksa None.
    """
    if combined is None or combined.empty:
        return None
    df = combined
    if codes is not None:
        df = df[df["Fon Kodu"].astype(str).isin([str(c) for c in codes])]
    if df.empty:
        return None
    piv = (df.pivot_table(index="Tarih", columns="Fon Kodu", values="Fiyat", aggfunc="last")
             .sort_index())
    if piv.shape[0] < 2:
        return None
    rets = piv.pct_change()
    n_per_day = rets.notna().sum(axis=1)
    med = rets.median(axis=1).where(n_per_day >= min_funds, 0.0)
    med = med.iloc[1:]                      # ilk satır pct_change NaN
    if med.empty:
        return None
    path = 100.0 * (1.0 + med.fillna(0.0)).cumprod()
    first = pd.Series([100.0], index=[piv.index[0]])
    return pd.concat([first, path])

"""
Ortak G/Ç yardımcıları: encoding'i bir kez ayarla, Türkçe sayı/CSV oku.

v1'de UTF-8 stdout düzeltmesi her script'in başında tekrar ediyordu ve Türkçe
float ayrıştırma ETL içine gömülüydü. Burada tek yerde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import config


def setup_utf8() -> None:
    """Windows konsolundaki (cp1254) Türkçe karakter çökmelerini önle. Idempotent."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def parse_turkish_float(value) -> float:
    """
    Türkçe ('3.244,52') veya standart ('3244.52') sayıyı float'a çevirir.
    Ondalık ayracı otomatik algılanır.
    """
    if pd.isna(value) or str(value).strip() == "":
        return np.nan
    s = str(value).replace('"', "").strip()
    if s == "":
        return np.nan

    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        if s.rindex(",") > s.rindex("."):     # virgül ondalık: 3.244,52
            s = s.replace(".", "").replace(",", ".")
        else:                                  # nokta ondalık: 3,244.52
            s = s.replace(",", "")
    elif has_comma:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return np.nan


_COLUMN_NORMALIZE = {
    "Fon Adı": "Fon Adi",
    "Fon Toplam Değer": "Fon Toplam Deger",
    "Tedavüldeki Pay Sayısı": "Tedavuldeki Pay Sayisi",
    "Kişi Sayısı": "Kisi Sayisi",
}
_NUMERIC_COLS = ["Fiyat", "Fon Toplam Deger", "Tedavuldeki Pay Sayisi", "Kisi Sayisi"]


def _detect_skiprows(path: Path) -> int:
    """İlk satır 'Fon Kodu' içeriyorsa yeni format (skiprows=0), değilse eski (3)."""
    for enc in ("utf-8-sig", "utf-8", "cp1254"):
        try:
            with open(path, encoding=enc) as f:
                return 0 if "Fon Kodu" in f.readline() else 3
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 3


def read_tefas_csv(path: Path) -> pd.DataFrame:
    """
    Tek bir TEFAS CSV dosyasını okur (eski DD.MM.YYYY/virgül ve yeni
    YYYY-MM-DD/nokta formatlarının her ikisi de desteklenir).
    """
    path = Path(path)
    skiprows = _detect_skiprows(path)
    df = None
    for enc in config.CSV_READ_ENCODINGS:
        try:
            df = pd.read_csv(path, skiprows=skiprows, encoding=enc,
                             dtype=str, on_bad_lines="warn")
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {path.name} okunamadı ({enc}): {e}")
            return pd.DataFrame()
    if df is None:
        print(f"[ERROR] {path.name} hiçbir encoding ile okunamadı.")
        return pd.DataFrame()

    df.columns = [c.strip() for c in df.columns]
    df.rename(columns=_COLUMN_NORMALIZE, inplace=True)
    df.dropna(how="all", inplace=True)

    if skiprows == 0:
        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
    else:
        df["Tarih"] = pd.to_datetime(df["Tarih"], format="%d.%m.%Y", errors="coerce")

    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].map(parse_turkish_float)
    return df

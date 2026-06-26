"""
Veri kalitesi: bozuk fiyat serilerini (pay birimi/itibari değer değişimi, hatalı
tik, bölünme) tespit eder ve risk hesaplarını uç günlerden korur.

Saf fonksiyonlar — birim test edilebilir, yan etkisiz. v1 ile aynı mantık.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DATA_QUALITY_MAX_DAILY_MOVE, DAILY_RETURN_CLIP

QUALITY_OK = "OK"
QUALITY_SUSPECT = "SUSPECT_JUMP"
QUALITY_INSUFFICIENT = "INSUFFICIENT"


def daily_returns_pct(prices) -> np.ndarray:
    """Pozitif fiyatlardan günlük % getiri (NaN/inf temizli)."""
    s = pd.Series(prices, dtype="float64")
    r = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna() * 100.0
    return r.to_numpy()


def screen_price_series(prices, min_points: int = 20,
                        max_daily_move: float = DATA_QUALITY_MAX_DAILY_MOVE) -> dict:
    """Tek bir fonun fiyat serisini kalite açısından değerlendirir."""
    arr = np.asarray(prices, dtype="float64")
    valid = arr[(~np.isnan(arr)) & (arr > 0)]
    n = int(valid.size)

    if n < min_points:
        return {"quality": QUALITY_INSUFFICIENT, "max_daily_move": np.nan,
                "n_points": n, "reason": f"Yetersiz gozlem ({n} < {min_points})"}

    daily = daily_returns_pct(valid)
    if daily.size == 0:
        return {"quality": QUALITY_INSUFFICIENT, "max_daily_move": np.nan,
                "n_points": n, "reason": "Gunluk getiri hesaplanamadi"}

    max_move = float(np.nanmax(np.abs(daily)))
    if max_move > max_daily_move:
        return {"quality": QUALITY_SUSPECT, "max_daily_move": round(max_move, 2),
                "n_points": n,
                "reason": f"Tek gunluk hareket %{max_move:.1f} > esik %{max_daily_move:.0f}"}

    return {"quality": QUALITY_OK, "max_daily_move": round(max_move, 2),
            "n_points": n, "reason": "OK"}


def clean_daily_returns(returns, clip: float = DAILY_RETURN_CLIP) -> pd.Series:
    """Günlük getirileri ±clip bandına winsorize eder (ikinci moment hesapları için)."""
    s = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if clip and clip > 0:
        s = s.clip(lower=-clip, upper=clip)
    return s

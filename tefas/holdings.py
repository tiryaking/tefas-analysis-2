"""
Kişisel portföy takibi: işlem defteri (ALIS/SATIS) -> pozisyon, değerleme, getiri.

İşlemler proje kökündeki `portfolio_transactions.csv` dosyasında tutulur
(elle/Excel'le düzenlenebilir; utf-8-sig, Türkçe ondalık desteklenir):

    Tarih,Fon Kodu,Islem,Adet,Fiyat,Not
    2025-03-10,PRY,ALIS,1250.5,4.8210,ilk alım

Tasarım (ev stili): matematik saf fonksiyonlarda (frame girer, frame/dict
çıkar); dosya G/Ç yalnızca `load_transactions` / `append_score_history`'de.
TEFAS fonlarında temettü yoktur ve ücretler NAV içindedir — işlem türü olarak
yalnızca ALIS/SATIS yeterlidir. Getiri iki ölçüyle raporlanır:

- **XIRR** (para-ağırlıklı): "benim param ne kazandı" — düzensiz katkılarda
  dürüst manşet sayı. Saf-numpy bisection; scipy bağımlılığı yok.
- **TWR** (zaman-ağırlıklı, günlük zincirleme): fon/benchmark kıyası için —
  katkı zamanlaması etkisini arındırır.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .io_utils import parse_turkish_float

TXN_COLUMNS = ["Tarih", "Fon Kodu", "Islem", "Adet", "Fiyat", "Not"]
VALID_ISLEM = ("ALIS", "SATIS")

# Değerlemede son NAV bu kadar takvim gününden eskiyse pozisyon "bayat veri"
# olarak işaretlenir (fon fiyatlanmıyor / veri seti güncel değil olabilir).
STALE_NAV_DAYS = 7


# ─── İşlem defteri ────────────────────────────────────────────────────────────

def load_transactions(path: Path | None = None) -> pd.DataFrame:
    """İşlem defterini oku, doğrula ve normalize et (tarih sıralı döner).

    Hatalı satırlar sessizce atlanmaz: tüm sorunlar toplanıp tek bir
    ValueError ile satır numaralarıyla raporlanır (kısmi/yanlış P&L yerine
    gürültülü başarısızlık).
    """
    p = Path(path) if path is not None else config.DEFAULT_TRANSACTIONS_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"İşlem dosyası yok: {p}\n"
            f"Örnek için bkz. portfolio_transactions.example.csv")
    raw = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in TXN_COLUMNS[:5] if c not in raw.columns]  # Not opsiyonel
    if missing:
        raise ValueError(f"{p.name}: eksik kolon(lar): {', '.join(missing)}")
    if "Not" not in raw.columns:
        raw["Not"] = ""
    raw = raw.dropna(how="all").reset_index(drop=True)

    # Tarih: ISO (YYYY-MM-DD) öncelikli, eski TEFAS biçimi (DD.MM.YYYY) yedek.
    # `format="mixed"` bilerek kullanılmıyor: gün/ay sırası belirsizliği olmasın.
    t = raw["Tarih"].astype(str).str.strip()
    dates = pd.to_datetime(t, format="%Y-%m-%d", errors="coerce")
    fallback = dates.isna()
    if fallback.any():
        dates[fallback] = pd.to_datetime(t[fallback], format="%d.%m.%Y", errors="coerce")

    df = pd.DataFrame({
        "Tarih": dates,
        "Fon Kodu": raw["Fon Kodu"].str.strip().str.upper(),
        "Islem": raw["Islem"].str.strip().str.upper(),
        "Adet": raw["Adet"].map(parse_turkish_float),
        "Fiyat": raw["Fiyat"].map(parse_turkish_float),
        "Not": raw["Not"].fillna(""),
    })

    errors = []
    for i, row in df.iterrows():
        line = i + 2  # başlık satırı + 1-indeks
        if pd.isna(row["Tarih"]):
            errors.append(f"satır {line}: geçersiz tarih '{raw.loc[i, 'Tarih']}'")
        if not row["Fon Kodu"]:
            errors.append(f"satır {line}: boş fon kodu")
        if row["Islem"] not in VALID_ISLEM:
            errors.append(f"satır {line}: Islem 'ALIS' ya da 'SATIS' olmalı ('{raw.loc[i, 'Islem']}')")
        if not (row["Adet"] > 0):
            errors.append(f"satır {line}: Adet pozitif sayı olmalı ('{raw.loc[i, 'Adet']}')")
        if not (row["Fiyat"] > 0):
            errors.append(f"satır {line}: Fiyat pozitif sayı olmalı ('{raw.loc[i, 'Fiyat']}')")
    if errors:
        raise ValueError(f"{p.name} doğrulama hataları:\n  " + "\n  ".join(errors))

    return df.sort_values(["Tarih", "Fon Kodu"], kind="stable").reset_index(drop=True)


# ─── Pozisyonlar (FIFO) ───────────────────────────────────────────────────────

def positions(txns: pd.DataFrame) -> pd.DataFrame:
    """FIFO lot eşlemesiyle fon başına pozisyon ve realize K/Z.

    Dönen kolonlar: Fon Kodu, Adet (açık), Maliyet (açık lotların toplam
    maliyeti), Ortalama_Maliyet, Realize_KZ, Ilk_Alis, Son_Islem.
    Eldekinden fazla satış → ValueError (defter tutarsız demektir).
    """
    rows = []
    for code, grp in txns.groupby("Fon Kodu", sort=True):
        lots: list[list[float]] = []   # [kalan_adet, birim_fiyat]
        realized = 0.0
        for _, t in grp.iterrows():
            if t["Islem"] == "ALIS":
                lots.append([float(t["Adet"]), float(t["Fiyat"])])
                continue
            remain = float(t["Adet"])
            while remain > 1e-9:
                if not lots:
                    raise ValueError(
                        f"{code}: {t['Tarih'].date()} tarihli satış eldekinden fazla "
                        f"({remain:g} adet karşılıksız) — işlem defterini kontrol edin.")
                take = min(remain, lots[0][0])
                realized += take * (float(t["Fiyat"]) - lots[0][1])
                lots[0][0] -= take
                remain -= take
                if lots[0][0] <= 1e-9:
                    lots.pop(0)
        units = sum(l[0] for l in lots)
        cost = sum(l[0] * l[1] for l in lots)
        rows.append({
            "Fon Kodu": code,
            "Adet": round(units, 6),
            "Maliyet": round(cost, 2),
            "Ortalama_Maliyet": round(cost / units, 6) if units > 0 else np.nan,
            "Realize_KZ": round(realized, 2),
            "Ilk_Alis": grp["Tarih"].min(),
            "Son_Islem": grp["Tarih"].max(),
        })
    return pd.DataFrame(rows)


def valuation(pos: pd.DataFrame, combined: pd.DataFrame) -> pd.DataFrame:
    """Pozisyonlara güncel NAV, değer, K/Z ve ağırlık ekler.

    NAV veri setinde bulunamayan (delist/yazım hatası) kodlar NaN değerle
    döner ve `Veri_Bayat=True` ile işaretlenir — çökmek yerine bayrak.
    """
    df = pos.copy()
    if df.empty:
        return df
    last = (combined.sort_values("Tarih")
            .groupby("Fon Kodu")[["Tarih", "Fiyat"]].last())
    as_of = pd.to_datetime(combined["Tarih"]).max()

    df["Son_Fiyat"] = df["Fon Kodu"].map(last["Fiyat"])
    df["Son_Tarih"] = df["Fon Kodu"].map(last["Tarih"])
    df["Deger"] = (df["Adet"] * df["Son_Fiyat"]).round(2)
    df["Deger_KZ"] = (df["Deger"] - df["Maliyet"]).round(2)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["Getiri_Pct"] = np.where(df["Maliyet"] > 0,
                                    (df["Deger_KZ"] / df["Maliyet"]) * 100, np.nan).round(2)
    stale = (as_of - df["Son_Tarih"]).dt.days > STALE_NAV_DAYS
    df["Veri_Bayat"] = (df["Son_Fiyat"].isna() | stale.fillna(True))

    open_total = df.loc[df["Adet"] > 0, "Deger"].sum()
    df["Agirlik"] = np.where((df["Adet"] > 0) & (open_total > 0),
                             df["Deger"] / open_total, 0.0).round(4)
    return df


# ─── Getiri: XIRR (para-ağırlıklı) ───────────────────────────────────────────

def xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float:
    """Düzensiz nakit akışlarının iç verim oranı (yıllık, ondalık).

    Konvansiyon: yatırılan para negatif, çekilen/mevcut değer pozitif.
    Kök (-%99.9, +%1000) aralığında bisection ile aranır; aralıkta işaret
    değişimi yoksa (tanımsız/yakınsamıyor) NaN döner.
    """
    if len(cashflows) < 2:
        return np.nan
    dates = pd.to_datetime([c[0] for c in cashflows])
    amounts = np.asarray([c[1] for c in cashflows], dtype=float)
    if not ((amounts > 0).any() and (amounts < 0).any()):
        return np.nan
    years = (dates - dates.min()).days / 365.0

    def npv(rate: float) -> float:
        return float(np.sum(amounts / (1.0 + rate) ** years))

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if np.isnan(f_lo) or np.isnan(f_hi) or f_lo * f_hi > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or (hi - lo) < 1e-10:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def xirr_cashflows(txns: pd.DataFrame, current_value: float,
                   as_of: pd.Timestamp) -> list[tuple[pd.Timestamp, float]]:
    """İşlem defterinden XIRR girdisi üret: alışlar (-), satışlar (+),
    portföyün bugünkü değeri kapanış akışı (+) olarak eklenir."""
    flows = []
    for _, t in txns.iterrows():
        sign = -1.0 if t["Islem"] == "ALIS" else 1.0
        flows.append((t["Tarih"], sign * float(t["Adet"]) * float(t["Fiyat"])))
    if current_value > 0:
        flows.append((pd.Timestamp(as_of), float(current_value)))
    return flows


# ─── Getiri: TWR (zaman-ağırlıklı) ───────────────────────────────────────────

def portfolio_value_series(txns: pd.DataFrame, combined: pd.DataFrame) -> pd.DataFrame:
    """Günlük portföy değeri ve net dış akış serisi.

    NAV tarih ızgarası veri setinden gelir; işlem tarihi işlem gününe eşit ya
    da sonraki ilk NAV gününe "yapışır" (hafta sonu girilen işlem pazartesiye).
    Dönen kolonlar: `Deger` (gün sonu değer), `Net_Akis` (o gün ALIS−SATIS
    tutarı, işlem fiyatından).
    """
    codes = txns["Fon Kodu"].unique().tolist()
    sub = combined[combined["Fon Kodu"].isin(codes)]
    px = (sub.pivot_table(index="Tarih", columns="Fon Kodu",
                          values="Fiyat", aggfunc="last")
          .sort_index().ffill())
    px = px[px.index >= txns["Tarih"].min()]
    if px.empty:
        return pd.DataFrame(columns=["Deger", "Net_Akis"])

    idx = px.index
    delta = pd.DataFrame(0.0, index=idx, columns=px.columns)
    flows = pd.Series(0.0, index=idx)
    for _, t in txns.iterrows():
        loc = idx.searchsorted(t["Tarih"])
        if loc >= len(idx):        # veri setinin son gününden sonraki işlem
            loc = len(idx) - 1
        day = idx[loc]
        signed = float(t["Adet"]) if t["Islem"] == "ALIS" else -float(t["Adet"])
        delta.loc[day, t["Fon Kodu"]] += signed
        flows.loc[day] += signed * float(t["Fiyat"])   # ALIS + / SATIS − (işlem fiyatından)
    units = delta.cumsum()
    value = (units * px).sum(axis=1, skipna=True)
    return pd.DataFrame({"Deger": value, "Net_Akis": flows})


def twr(txns: pd.DataFrame, combined: pd.DataFrame) -> dict:
    """Günlük zincirlenmiş zaman-ağırlıklı getiri.

    Akış konvansiyonu: gün içi akışlar gün SONUNDA kabul edilir —
    r_t = (V_t − F_t) / V_{t−1} − 1. Portföyün boş olduğu (V_{t−1}=0) günler
    zinciri kırmaz, atlanır. Dönen: {"twr", "twr_yillik", "gun"} (ondalık;
    seri < 30 günse yıllıklandırma NaN).
    """
    series = portfolio_value_series(txns, combined)
    if len(series) < 2:
        return {"twr": np.nan, "twr_yillik": np.nan, "gun": 0}
    v, f = series["Deger"].to_numpy(), series["Net_Akis"].to_numpy()
    factors = []
    first_day, last_day = None, None
    for t in range(1, len(v)):
        if v[t - 1] <= 0:
            continue
        factors.append((v[t] - f[t]) / v[t - 1])
        if first_day is None:
            first_day = series.index[t - 1]
        last_day = series.index[t]
    if not factors:
        return {"twr": np.nan, "twr_yillik": np.nan, "gun": 0}
    total = float(np.prod(factors)) - 1.0
    days = (last_day - first_day).days
    annual = (1.0 + total) ** (365.0 / days) - 1.0 if days >= 30 else np.nan
    return {"twr": total, "twr_yillik": annual, "gun": days}


# ─── Sinyaller ───────────────────────────────────────────────────────────────

SIGNAL_DROP_PTS = 10.0        # persentil düşüş eşiği (puan)
SIGNAL_LOOKBACK_DAYS = 25     # kıyas alınacak en az bu kadar eski snapshot
TOP_QUARTILE = 75.0


def signals(codes: list[str], scored: pd.DataFrame,
            history: pd.DataFrame | None) -> list[dict]:
    """Elde tutulan fonlar için uyarı sinyalleri.

    Kurallar: (1) Overall persentili ~30 gün öncesine göre ≥ SIGNAL_DROP_PTS
    puan düştü; (2) üst çeyrekten (≥75) çıktı; (3) fon skor tablosunda yok
    (delist/filtre/şüpheli veri). Geçmişte < 2 snapshot varsa (1)-(2) yerine
    tek bir "yetersiz geçmiş" bilgi sinyali döner — hata değil.
    Dönen: [{"Fon Kodu", "Tip", "Mesaj"}] (Tip: UYARI | BILGI).
    """
    out = []
    scored_codes = set(scored["Fon Kodu"].astype(str)) if scored is not None else set()
    for code in codes:
        if code not in scored_codes:
            out.append({"Fon Kodu": code, "Tip": "UYARI",
                        "Mesaj": "Fon güncel skor tablosunda yok (delist / filtre dışı / şüpheli veri olabilir)."})

    if history is None or history.empty or history["Tarih"].nunique() < 2:
        out.append({"Fon Kodu": "—", "Tip": "BILGI",
                    "Mesaj": "Skor geçmişinde 2'den az tarih var — trend sinyalleri için "
                             "birkaç `tefas run` daha birikmeli (yetersiz geçmiş)."})
        return out

    hist = history.copy()
    hist["Tarih"] = pd.to_datetime(hist["Tarih"])
    dates = sorted(hist["Tarih"].unique())
    latest = dates[-1]
    older = [d for d in dates if d <= latest - pd.Timedelta(days=SIGNAL_LOOKBACK_DAYS)]
    prev = older[-1] if older else dates[0]   # ~30 gün öncesi; yoksa eldeki en eski
    cur_snap = hist[hist["Tarih"] == latest].set_index("Fon Kodu")["Overall_Persentil"]
    prev_snap = hist[hist["Tarih"] == prev].set_index("Fon Kodu")["Overall_Persentil"]
    gap_days = (latest - prev).days

    for code in codes:
        cur, old = cur_snap.get(code), prev_snap.get(code)
        if cur is None or old is None or pd.isna(cur) or pd.isna(old):
            continue
        if old - cur >= SIGNAL_DROP_PTS:
            out.append({"Fon Kodu": code, "Tip": "UYARI",
                        "Mesaj": f"Skor persentili {gap_days} günde {old:.0f} → {cur:.0f} "
                                 f"(-{old - cur:.0f} puan) düştü."})
        if old >= TOP_QUARTILE and cur < TOP_QUARTILE:
            out.append({"Fon Kodu": code, "Tip": "UYARI",
                        "Mesaj": f"Fon üst çeyrekten çıktı (persentil {old:.0f} → {cur:.0f})."})
    return out


# ─── Skor geçmişi (sinyaller için birikir) ───────────────────────────────────

SCORE_HISTORY_COLUMNS = ["Tarih", "Fon Kodu", "Overall_Score", "Overall_Persentil",
                         "Conservative_Score", "Balanced_Score",
                         "Moderate_Score", "Aggressive_Score"]


def score_snapshot(scored: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Skorlu tablodan tek-tarihlik geçmiş kaydı üretir (saf)."""
    snap = pd.DataFrame({"Tarih": pd.Timestamp(as_of),
                         "Fon Kodu": scored["Fon Kodu"].astype(str)})
    snap["Overall_Score"] = pd.to_numeric(scored["Overall_Score"], errors="coerce").values
    snap["Overall_Persentil"] = snap["Overall_Score"].rank(pct=True).mul(100).round(1)
    for col in SCORE_HISTORY_COLUMNS[4:]:
        snap[col] = (pd.to_numeric(scored[col], errors="coerce").values
                     if col in scored.columns else np.nan)
    return snap[SCORE_HISTORY_COLUMNS]


def append_score_history(snapshot: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Snapshot'ı geçmiş parquet'ine ekler; (Tarih, Fon Kodu) üzerinde son
    yazılan kazanır (aynı gün tekrar çalıştırma güncelleme sayılır)."""
    if path.exists():
        hist = pd.read_parquet(path)
        hist = pd.concat([hist, snapshot], ignore_index=True)
    else:
        hist = snapshot.copy()
    hist = (hist.drop_duplicates(subset=["Tarih", "Fon Kodu"], keep="last")
            .sort_values(["Tarih", "Fon Kodu"]).reset_index(drop=True))
    hist.to_parquet(path, index=False)
    return hist

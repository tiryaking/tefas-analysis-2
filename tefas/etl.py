"""
ETL: Dataset CSV'lerini tek bir temiz, birleşik DataFrame'e indirger.

FINDING #1 — v1 ETL bir CSV dosyasına yazıyor ve sonraki aşamalar onu tekrar
okuyordu. Burada `load_combined()` bir **DataFrame döndürür**; dosyaya yazma
isteğe bağlıdır (pipeline parquet olarak önbelleğe alır). Dedup mantığı v1 ile
aynı: (Fon Kodu, Tarih) üzerinde keep="last".
"""
from __future__ import annotations

import json

import pandas as pd

from . import config
from .io_utils import read_tefas_csv


def _turkish_norm(s: str) -> str:
    tr = {"İ": "i", "I": "ı", "Ğ": "ğ", "Ü": "ü", "Ş": "ş", "Ö": "ö", "Ç": "ç"}
    for u, l in tr.items():
        s = s.replace(u, l)
    return s.lower()


def active_fund_codes(platform_status_path) -> set[str]:
    """platform_status.json'dan TEFAS/BEFAS'ta işlem gören fon kodlarını döndürür."""
    with open(platform_status_path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        k for k, v in data.items()
        if not k.startswith("_")
        and "görmüyor" not in _turkish_norm(str(v.get("platform_durumu", "")))
        and not str(v.get("platform_durumu", "")).startswith("HATA")
    }


def _keyword_mask(series: pd.Series, keywords: list[str]) -> pd.Series:
    mask = series.str.contains(keywords[0], case=False, na=False, regex=False)
    for kw in keywords[1:]:
        mask = mask | series.str.contains(kw, case=False, na=False, regex=False)
    return mask


def load_combined(fund_type: str, *, include: list[str] | None = None,
                  exclude: list[str] | None = None,
                  active_only: bool = True) -> pd.DataFrame:
    """
    Bir fon tipi için tüm aylık CSV'leri oku, birleştir, dedup et, filtrele;
    temizlenmiş long-format DataFrame döndür.
    """
    paths = config.paths_for(fund_type)
    files = sorted(paths.dataset_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"CSV bulunamadı: {paths.dataset_dir}")

    print(f"[INFO] {len(files)} CSV okunuyor ({paths.fund_name})...")
    frames = [df for f in files if not (df := read_tefas_csv(f)).empty]
    if not frames:
        raise ValueError("Hiçbir CSV okunamadı.")

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined.drop_duplicates(subset=["Fon Kodu", "Tarih"], keep="last", inplace=True)
    combined.sort_values(["Fon Kodu", "Tarih"], inplace=True)
    combined.reset_index(drop=True, inplace=True)
    print(f"[INFO] Birleştirildi: {before:,} satır -> {len(combined):,} (dedup sonrası)")

    name_col = "Fon Adi" if "Fon Adi" in combined.columns else combined.columns[1]
    if include:
        combined = combined[_keyword_mask(combined[name_col], include)].copy()
        print(f"[INFO] Dahil filtresi: {combined['Fon Kodu'].nunique()} fon kaldı")
    if exclude:
        combined = combined[~_keyword_mask(combined[name_col], exclude)].copy()
        print(f"[INFO] Hariç filtresi: {combined['Fon Kodu'].nunique()} fon kaldı")

    if active_only:
        if paths.platform_status.exists():
            codes = active_fund_codes(paths.platform_status)
            before = combined["Fon Kodu"].nunique()
            combined = combined[combined["Fon Kodu"].isin(codes)].copy()
            print(f"[INFO] Aktif fon filtresi: {before} -> {combined['Fon Kodu'].nunique()} fon")
        else:
            # Sessiz WARN yeterince görünür değildi: aktiflik filtresi istenmişken
            # dosya yoksa YAT ve EMK evrenleri fark edilmeden farklı davranıyordu
            # (EMK'da kapanmış fonlar analize karışıyordu). Açıkça durdur.
            raise FileNotFoundError(
                f"platform_status dosyası yok: {paths.platform_status}\n"
                f"  Aktif-fon filtresi (active_only=True) bu dosya olmadan uygulanamaz. İki seçenek:\n"
                f"  1) Dosyayı üretin:  python GetDataSet/fetch_platform_status.py --fund-type {paths.fund_type}\n"
                f"  2) Filtreyi kapatın: `--no-active-only` bayrağı veya config'te \"active_only\": false\n"
                f"     (bu durumda kapanmış/işlem görmeyen fonlar da analize dahil olur — survivorship notuna bakın).")

    if combined.empty:
        raise ValueError("Filtrelerden sonra fon kalmadı.")
    return combined

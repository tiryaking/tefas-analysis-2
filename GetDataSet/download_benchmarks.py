"""
Benchmark Serisi Indirici (TCMB EVDS)
=====================================
Dataset/benchmarks/ altina `tefas/benchmarks.py`'nin bekledigi formatta
(`Tarih,Deger`; ISO tarih; utf-8-sig) gunluk endeks CSV'leri indirir:

  xu100.csv    BIST 100 kapanis
  altin.csv    Gram altin satis (TL, Istanbul serbest piyasa)
  usdtry.csv   USD/TRY satis kuru
  mevduat.csv  TL mevduat faizinden sentezlenen toplam-getiri ENDEKSI
               (oran degil; gunluk bilesik: I_t = I_{t-1} * (1 + oran/36500))

Kaynak: TCMB EVDS API (https://evds2.tcmb.gov.tr) — ucretsiz anahtar gerekir:
uye ol, profil sayfasindan "API Anahtari"ni al, sonra:

  set EVDS_API_KEY=...     (veya tefas.config.json'a "evds_api_key" ekle)

Kullanim:
  python download_benchmarks.py                    # son 24 ay
  python download_benchmarks.py --start 2025-01-01
  python download_benchmarks.py --update           # mevcut CSV'nin son tarihinden devam
  python download_benchmarks.py --series xu100 usdtry

Basarisizlik davranisi: yeni veri gecici dosyaya yazilir ve yalnizca basari
halinde atomik olarak yerine gecer — HTTP hatasi eski CSV'yi bozmaz.
Pipeline benchmark'lari OPSIYONEL kabul eder; bu script hic calistirilmasa da
`tefas run` aynen calisir (Beta/Alpha/TE/IR NaN kalir).
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
BENCH_DIR = PROJECT_ROOT / "Dataset" / "benchmarks"
CONFIG_PATH = PROJECT_ROOT / "tefas.config.json"

EVDS_URL = "https://evds2.tcmb.gov.tr/service/evds/"

# EVDS seri kodlari tek yerde: kod degisir/kapanirsa yalnizca bu tablo guncellenir.
# kind: "level" = seri dogrudan endeks/fiyat; "rate" = yillik % faiz, endekse
# sentezlenir (bkz. deposit_index).
SERIES = {
    "xu100":   {"code": "TP.MK.F.BILESIK", "kind": "level",
                "label": "BIST 100 kapanis"},
    "altin":   {"code": "TP.MK.KUL.YTL",   "kind": "level",
                "label": "Kulce altin satis TL/gram"},
    "usdtry":  {"code": "TP.DK.USD.S.YTL", "kind": "level",
                "label": "USD/TRY satis"},
    "mevduat": {"code": "TP.TRY.MT03",     "kind": "rate",
                "label": "TL mevduat faizi (3 aya kadar, %) -> endeks"},
}


def get_api_key() -> str | None:
    """EVDS anahtari: once EVDS_API_KEY ortam degiskeni, sonra tefas.config.json."""
    key = os.environ.get("EVDS_API_KEY", "").strip()
    if key:
        return key
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        key = str(cfg.get("evds_api_key", "")).strip()
        return key or None
    except Exception:
        return None


def fetch_series(code: str, start: datetime, end: datetime, api_key: str,
                 max_retries: int = 3) -> list[dict] | None:
    """EVDS'ten tek seriyi ceker; `items` listesini dondurur (None = basarisiz)."""
    url = (f"{EVDS_URL}series={quote(code)}"
           f"&startDate={start.strftime('%d-%m-%Y')}"
           f"&endDate={end.strftime('%d-%m-%Y')}&type=json")
    for attempt in range(1, max_retries + 1):
        try:
            req = Request(url, headers={"key": api_key,
                                        "User-Agent": "tefas-benchmarks/1.0"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
        except HTTPError as e:
            print(f"    [HATA] HTTP {e.code} - Deneme {attempt}/{max_retries}"
                  + (" (anahtar gecersiz olabilir)" if e.code in (401, 403, 500) else ""))
        except URLError as e:
            print(f"    [HATA] Baglanti: {e.reason} - Deneme {attempt}/{max_retries}")
        except Exception as e:  # noqa: BLE001
            print(f"    [HATA] {e} - Deneme {attempt}/{max_retries}")
        if attempt < max_retries:
            time.sleep(2 * attempt)
    return None


# ─── Saf donusumler (testte canned JSON ile dogrulanir, ag gerekmez) ─────────

def parse_items(items: list[dict], code: str) -> list[tuple[str, float]]:
    """EVDS `items` -> [(ISO tarih, deger)]; null/bos gunler atlanir.

    EVDS, item anahtarinda seri kodundaki noktalari alt cizgiye cevirir
    (TP.DK.USD.S.YTL -> TP_DK_USD_S_YTL); tarih 'dd-mm-yyyy' gelir.
    """
    key = code.replace(".", "_")
    rows = []
    for it in items or []:
        raw = it.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(str(raw).replace(",", "."))
            date = datetime.strptime(it["Tarih"], "%d-%m-%Y").strftime("%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        rows.append((date, value))
    return sorted(rows)


def deposit_index(rate_rows: list[tuple[str, float]],
                  base: float = 100.0) -> list[tuple[str, float]]:
    """Yillik % faiz gozlemlerinden gunluk bilesik toplam-getiri endeksi.

    Gozlemler arasindaki her takvim gunu icin son bilinen oranla bileşir:
    I_t = I_{t-1} * (1 + oran/36500). Ilk gozlem gunu = taban (100).
    """
    if not rate_rows:
        return []
    out = [(rate_rows[0][0], base)]
    idx = base
    prev_date = datetime.strptime(rate_rows[0][0], "%Y-%m-%d")
    prev_rate = rate_rows[0][1]
    for date_str, rate in rate_rows[1:]:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        days = (d - prev_date).days
        idx *= (1.0 + prev_rate / 36500.0) ** days
        out.append((date_str, round(idx, 6)))
        prev_date, prev_rate = d, rate
    return out


def merge_rows(old_rows: list[tuple[str, float]],
               new_rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Eski + yeni gozlemleri tarih uzerinde birlestirir (yeni olan kazanir)."""
    merged = dict(old_rows)
    merged.update(dict(new_rows))
    return sorted(merged.items())


# ─── CSV G/C ─────────────────────────────────────────────────────────────────

def read_csv_rows(path: Path) -> list[tuple[str, float]]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rows.append((row["Tarih"], float(str(row["Deger"]).replace(",", "."))))
            except (KeyError, ValueError):
                continue
    return sorted(rows)


def write_csv_atomic(path: Path, rows: list[tuple[str, float]]) -> None:
    """Gecici dosyaya yaz, sonra atomik degistir — hata eski CSV'yi bozmaz."""
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Tarih", "Deger"])
        w.writerows(rows)
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="TCMB EVDS benchmark indirici")
    parser.add_argument("--start", type=str, default=None, help="Baslangic (YYYY-MM-DD)")
    parser.add_argument("--months", type=int, default=24, help="Kac ay geriye (varsayilan 24)")
    parser.add_argument("--update", action="store_true",
                        help="Her serinin mevcut CSV'sindeki son tarihten devam et")
    parser.add_argument("--series", nargs="+", choices=sorted(SERIES),
                        default=sorted(SERIES), help="Indirilecek seriler")
    parser.add_argument("--delay", type=float, default=1.0, help="Istekler arasi bekleme (sn)")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("[HATA] EVDS API anahtari bulunamadi.\n"
              "       1) https://evds2.tcmb.gov.tr adresinde ucretsiz uye olun,\n"
              "       2) profil sayfanizdan API anahtarinizi alin,\n"
              "       3) `set EVDS_API_KEY=...` ya da tefas.config.json'a "
              "\"evds_api_key\" anahtari ekleyin.")
        return 1

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now()
    default_start = (datetime.strptime(args.start, "%Y-%m-%d") if args.start
                     else today - timedelta(days=args.months * 30))

    print("=" * 60)
    print("  TCMB EVDS Benchmark Indirici")
    print("=" * 60)

    failures = 0
    for name in args.series:
        spec = SERIES[name]
        out_path = BENCH_DIR / f"{name}.csv"
        # `mevduat` icin ham ORANLAR ayri tutulur; endeks bastan sentezlenir ki
        # --update ile eklenen oranlar bileşik zinciri bozmasin.
        raw_path = BENCH_DIR / f"_{name}_oran.csv" if spec["kind"] == "rate" else out_path
        old_rows = read_csv_rows(raw_path)

        start = default_start
        if args.update and old_rows:
            last = datetime.strptime(old_rows[-1][0], "%Y-%m-%d")
            start = last + timedelta(days=1)
            if start.date() > today.date():
                print(f"[{name}] Zaten guncel ({old_rows[-1][0]}).")
                continue

        print(f"\n[{name}] {spec['label']}  ({spec['code']})")
        print(f"    {start.date()} -> {today.date()}")
        items = fetch_series(spec["code"], start, today, api_key)
        if items is None:
            print(f"    [WARN] Indirilemedi — mevcut {out_path.name} korunuyor.")
            failures += 1
            continue
        new_rows = parse_items(items, spec["code"])
        if not new_rows:
            print("    [WARN] Yeni gozlem yok.")
            continue
        merged = merge_rows(old_rows, new_rows)
        if spec["kind"] == "rate":
            write_csv_atomic(raw_path, merged)          # ham oranlar (dahili)
            write_csv_atomic(out_path, deposit_index(merged))
        else:
            write_csv_atomic(out_path, merged)
        print(f"    -> {len(new_rows)} yeni gozlem, toplam {len(merged)}: {out_path.name}")
        time.sleep(args.delay)

    print("\n" + "=" * 60)
    if failures:
        print(f"  TAMAMLANDI (hatali seri: {failures}) — eski CSV'ler korundu.")
    else:
        print("  TAMAMLANDI")
    print(f"  Klasor: {BENCH_DIR}")
    print("  Simdi `tefas run` calistirin: Beta/Alpha/TE/IR hesaplanacak.")
    print("=" * 60)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

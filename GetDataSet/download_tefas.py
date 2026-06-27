"""
TEFAS Veri Seti Indirici
========================
Aylik parcalarda son 1 yillik veriyi API'dan indirir.
Cikti: Dataset/Yatirim/ veya Dataset/Emeklilik/ klasoru altinda CSV dosyalari.

Kullanim:
  python download_tefas.py                    # Son 1 yil, YATirim fonlari
  python download_tefas.py --fund-type EMK    # Emeklilik fonlari
  python download_tefas.py --months 6         # Son 6 ay
  python download_tefas.py --start 2025-01-01 # Belirli tarihten itibaren
  python download_tefas.py --update           # Mevcut veri setindeki en son tarihten bugune eksikleri indir
  python download_tefas.py --update --fund-type EMK  # Emeklilik fonlari icin eksikleri indir
"""

import argparse
import time
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ── Yollar ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR = PROJECT_ROOT / "Dataset"

# ── Fon Tipi Haritasi ──
FUND_TYPE_MAP = {
    "YAT": "Yatirim",
    "EMK": "Emeklilik",
}

def get_fund_type_folder(fund_type: str) -> str:
    """Fon tipine göre alt klasör adını döndür."""
    return FUND_TYPE_MAP.get(fund_type.upper(), "Yatirim")

def get_fund_type_interactive() -> str:
    """Kullanıcıya fon tipini sor (CLI'dan gelmiyorsa)."""
    print("\n[*] Fon Tipi Secimi:")
    print("  1. YATirim Fonlari (YAT)")
    print("  2. EMKlilik Fonlari (EMK)")
    
    choice = input("\nSeciminiz (1/2) [1]: ").strip() or "1"
    
    if choice == '2':
        return "EMK"
    return "YAT"

# ── API Ayarlari ──
API_URL = "https://www.tefas.gov.tr/api/funds/fonGnlBlgSiraliGetirDosya"
TOKEN = "Bearer ST-tefaswebwse3irfmSBj4iRAzGPbAlS94Se"
DEVICE_ID = "a700557e-4bdd-4fc1-abb1-b941c352a7fc.FnRVcGVTWbT_cnZgITo3EGtVPiv6Zle1HVw9yd8erQ0"

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Authorization": TOKEN,
    "Cache-Control": "no-cache",
    "Connection": "keep-keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://www.tefas.gov.tr",
    "Pragma": "no-cache",
    "Referer": "https://www.tefas.gov.tr/tr/fon-verileri?fundType=YAT",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "x-request-id": "2b55e8c1-675a-444b-9a83-a2b0a4900e14",
}

COOKIES = (
    "tefas.clientDeviceId=" + DEVICE_ID
)


def fetch_month(start_date: str, end_date: str, fund_type: str = "YAT", max_retries: int = 3) -> dict | None:
    """
    Belirli bir tarih araligi icin API'dan veri ceker.
    Tarih formati: YYYYMMDD
    """
    payload = json.dumps({
        "dil": "TR",
        "fonTipi": fund_type,
        "fonKod": None,
        "fonGrup": None,
        "basTarih": start_date,
        "bitTarih": end_date,
        "fonTurKod": None,
        "fonUnvanTip": None,
        "kurucuKod": None,
        "fonTurAciklama": None,
        "sfonTurKod": None,
    }).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        try:
            req = Request(API_URL, data=payload, headers=HEADERS, method="POST")
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except HTTPError as e:
            print(f"    [HATA] HTTP {e.code} - Deneme {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
        except URLError as e:
            print(f"    [HATA] Baglanti: {e.reason} - Deneme {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
        except Exception as e:
            print(f"    [HATA] {e} - Deneme {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
    return None


COLUMN_MAP = {
    "fonKodu": "Fon Kodu",
    "fonUnvan": "Fon Adi",
    "tarih": "Tarih",
    "fiyat": "Fiyat",
    "tedPaySayisi": "Tedavuldeki Pay Sayisi",
    "kisiSayisi": "Kisi Sayisi",
    "portfoyBuyukluk": "Fon Toplam Deger",
    "borsaBultenFiyat": "Borsa Bulten Fiyat",
}

TARGET_ORDER = ["Fon Kodu", "Fon Adi", "Tarih", "Fiyat", "Tedavuldeki Pay Sayisi", "Kisi Sayisi", "Fon Toplam Deger"]


def save_csv(data: dict, filepath: Path) -> int:
    """API yanitini CSV dosyasina kaydeder. Kaydedilen satir sayisini dondurur."""
    if not data or "resultList" not in data:
        return 0

    records = data["resultList"]
    if not records:
        return 0

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=TARGET_ORDER, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            mapped = {}
            for api_key, val in rec.items():
                csv_key = COLUMN_MAP.get(api_key, api_key)
                mapped[csv_key] = val
            writer.writerow(mapped)

    return len(records)


def find_latest_date_in_csvs(output_dir: Path) -> datetime | None:
    """
    Belirtilen klasordeki tum CSV dosyalarini tarar ve 'Tarih' sutunundaki
    en yeni (en buyuk) tarihi dondurur. Hic veri yoksa None dondurur.
    """
    latest_date = None
    
    for csv_file in output_dir.glob("*.csv"):
        try:
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tarih_str = row.get("Tarih", "").strip()
                    if tarih_str:
                        try:
                            dt = datetime.strptime(tarih_str, "%Y-%m-%d")
                            if latest_date is None or dt > latest_date:
                                latest_date = dt
                        except ValueError:
                            continue
        except Exception as e:
            print(f"  [UYARI] {csv_file.name} okunamadi: {e}")
            continue
    
    return latest_date


def generate_month_ranges(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Iki tarih arasini aylik parcalara boler."""
    ranges = []
    current = start

    while current < end:
        # Ayin son gunu veya end tarihi
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        period_end = min(next_month - timedelta(days=1), end)

        ranges.append((current, period_end))
        current = next_month

    return ranges


def main():
    parser = argparse.ArgumentParser(description="TEFAS Veri Seti Indirici")
    parser.add_argument("--months", type=int, default=12, help="Kac aylik veri indirilecek (varsayilan: 12)")
    parser.add_argument("--start", type=str, default=None, help="Baslangic tarihi (YYYY-MM-DD)")
    parser.add_argument("--fund-type", type=str, default=None, choices=['YAT', 'EMK'], 
                        help="Fon tipi: YAT (Yatirim) veya EMK (Emeklilik). Belirtilmezse sorulur.")
    parser.add_argument("--delay", type=float, default=2.0, help="Istekler arasi bekleme suresi saniye (varsayilan: 2.0)")
    parser.add_argument("--update", action="store_true", 
                        help="Mevcut veri setindeki en son tarihten bugune eksik gunleri indir")
    args = parser.parse_args()

    # Fon tipi belirleme
    if args.fund_type is None:
        args.fund_type = get_fund_type_interactive()
    
    fund_type_folder = get_fund_type_folder(args.fund_type)
    
    # Cikti klasorunu ayarla
    OUTPUT_DIR = DATASET_DIR / fund_type_folder
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Tarih hesaplama
    today = datetime.now()
    
    if args.update:
        # --update modu: mevcut veri setinden en son tarihi bul, oradan devam et
        if args.start or args.months != 12:
            print("[UYARI] --update parametresi aktif; --start ve --months parametreleri yok sayiliyor.\n")
        
        print("[*] Mevcut veri seti taranıyor...")
        latest_date = find_latest_date_in_csvs(OUTPUT_DIR)
        
        if latest_date is None:
            print("[!] Mevcut veri setinde hic veri bulunamadi.")
            print(f"[*] Varsayilan olarak son {args.months} aylik veri indiriliyor...")
            start_date = today - timedelta(days=args.months * 30)
        else:
            start_date = latest_date + timedelta(days=1)
            print(f"[*] Veri setindeki en son tarih: {latest_date.date()}")
            
            if start_date.date() >= today.date():
                print("[*] Veri seti zaten guncel! Indirilecek yeni veri yok.")
                return
    elif args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        start_date = today - timedelta(days=args.months * 30)

    # Fon tipi guncelle
    HEADERS["Referer"] = f"https://www.tefas.gov.tr/tr/fon-verileri?fundType={args.fund_type}"

    month_ranges = generate_month_ranges(start_date, today)

    print("=" * 60)
    print("  TEFAS Veri Seti Indirici")
    print("=" * 60)
    print(f"  Tarih Araligi : {start_date.date()} -> {today.date()}")
    print(f"  Fon Tipi      : {args.fund_type} ({fund_type_folder})")
    print(f"  Ay Sayisi     : {len(month_ranges)}")
    print(f"  Cikti Klasoru : {OUTPUT_DIR}")
    print("=" * 60)

    total_rows = 0
    success_count = 0

    for i, (m_start, m_end) in enumerate(month_ranges, 1):
        bas = m_start.strftime("%Y%m%d")
        bit = m_end.strftime("%Y%m%d")
        filename = f"{m_start.strftime('%Y-%m-%d')}_{m_end.strftime('%Y-%m-%d')}.csv"
        filepath = OUTPUT_DIR / filename

        print(f"\n[{i}/{len(month_ranges)}] {bas} -> {bit}")

        # Eger dosya zaten varsa atla
        if filepath.exists():
            print(f"  -> Zaten mevcut, atlandi: {filename}")
            continue

        data = fetch_month(bas, bit, fund_type=args.fund_type)
        if data is None:
            print(f"  -> Basarisiz!")
            continue

        count = save_csv(data, filepath)
        total_rows += count
        success_count += 1
        print(f"  -> {count:,} satir kaydedildi: {filename}")

        # Sonraki istek icin bekle
        if i < len(month_ranges):
            time.sleep(args.delay)

    # ── Ozet ──
    print("\n" + "=" * 60)
    print("  TAMAMLANDI")
    print("=" * 60)
    print(f"  Basarili Ay    : {success_count}/{len(month_ranges)}")
    print(f"  Toplam Satir   : {total_rows:,}")
    print(f"  Dosya Sayisi   : {len(list(OUTPUT_DIR.glob('*.csv')))}")
    print("=" * 60)


if __name__ == "__main__":
    main()
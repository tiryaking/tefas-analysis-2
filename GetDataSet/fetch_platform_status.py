"""
TEFAS Platform Durumu Çekici (cloudscraper tabanlı)
====================================================
Tüm fonların tefas.gov.tr detay sayfasından "Platform Durumu" bilgisini çeker.
cloudscraper kullanarak F5 Shape Security WAF'ını aşar.

Kullanim:
  python fetch_platform_status.py                          # Tüm YAT fonlarını çek
  python fetch_platform_status.py --fund-type EMK          # Emeklilik fonları
  python fetch_platform_status.py --update                 # Sadece yeni/eksik fonlar
  python fetch_platform_status.py --limit 10               # Test için ilk 10 fon
  python fetch_platform_status.py --delay 0.5              # İstekler arası bekleme
  python GetDataSet/fetch_platform_status.py --fund-type YAT
  python GetDataSet/fetch_platform_status.py --fund-type YAT --update
  """

import argparse
import json
import re
import sys
import time
from pathlib import Path
from datetime import datetime

# Windows konsolunda Türkçe karakter hatasını önle
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cloudscraper

# ─── Yollar ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR = PROJECT_ROOT / "Dataset"
STATUS_DIR = DATASET_DIR / "platform_status"

FUND_TYPE_MAP = {"YAT": "Yatirim", "EMK": "Emeklilik"}

def get_status_file(fund_type: str) -> Path:
    """Fon tipine göre platform_status JSON dosya yolunu döndür."""
    folder = FUND_TYPE_MAP.get(fund_type.upper(), "Yatirim")
    return STATUS_DIR / f"platform_status_{folder.lower()}.json"

# TEFAS API kimlik bilgileri (download_tefas.py ile aynı)
TOKEN = "Bearer ST-tefaswebwse3irfmSBj4iRAzGPbAlS94Se"
DEVICE_ID = "a700557e-4bdd-4fc1-abb1-b941c352a7fc.FnRVcGVTWbT_cnZgITo3EGtVPiv6Zle1HVw9yd8erQ0"

# ─── Yardımcı İşlevler ────────────────────────────────────────────────────────
def load_existing_status(fund_type: str) -> dict:
    """Mevcut platform_status.json'u yükle."""
    path = get_status_file(fund_type)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            return {}
    return {}


def _turkish_normalize(text: str) -> str:
    """Türkçe karakterleri case-insensitive karşılaştırma için normalize eder.
    İ→i, I→ı dönüşümünü yapar, sonra lower() uygular."""
    tr_map = {
        'İ': 'i', 'I': 'ı',  # Türkçe I sorunu
        'Ğ': 'ğ', 'Ü': 'ü', 'Ş': 'ş', 'Ö': 'ö', 'Ç': 'ç',
    }
    result = text
    for upper, lower in tr_map.items():
        result = result.replace(upper, lower)
    return result.lower()


def save_status(data: dict, fund_type: str):
    """Dictionary'yi platform_status.json'a kaydet, _meta güncelle."""
    fon_list = {k: v for k, v in data.items() if not k.startswith("_")}
    islem_goren = sum(
        1 for v in fon_list.values()
        if "görmüyor" not in _turkish_normalize(str(v.get("platform_durumu", "")))
        and not str(v.get("platform_durumu", "")).startswith("HATA")
    )
    islem_gormeyen = sum(
        1 for v in fon_list.values()
        if "işlem görmüyor" in _turkish_normalize(str(v.get("platform_durumu", "")))
    )
    hata = sum(
        1 for v in fon_list.values()
        if str(v.get("platform_durumu", "")).startswith("HATA")
    )

    data["_meta"] = {
        "son_guncelleme": datetime.now().isoformat(timespec="seconds"),
        "toplam_fon": len(fon_list),
        "islem_goren": islem_goren,
        "islem_gormeyen": islem_gormeyen,
        "hata": hata,
    }

    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    path = get_status_file(fund_type)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def collect_fund_codes(fund_type: str) -> list[tuple[str, str]]:
    """Dataset CSV'lerinden unique (Fon Kodu, Fon Adi) toplar."""
    source_dir = DATASET_DIR / FUND_TYPE_MAP.get(fund_type.upper(), "Yatirim")
    if not source_dir.exists():
        print(f"[HATA] Klasör bulunamadı: {source_dir}")
        return []

    import csv
    funds = {}

    csv_files = sorted(source_dir.glob("*.csv"))
    print(f"[INFO] {len(csv_files)} CSV taranıyor: {source_dir}")

    for f in csv_files:
        try:
            with open(f, "r", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    kod = row.get("Fon Kodu", "").strip()
                    adi = row.get("Fon Adi", "").strip()
                    if kod and kod not in funds:
                        funds[kod] = adi
        except Exception as e:
            print(f"  [UYARI] {f.name}: {e}")

    result = [(k, v) for k, v in sorted(funds.items())]
    print(f"[INFO] {len(result)} unique fon bulundu.")
    return result


def parse_platform_durumu(html: str) -> str:
    """
    Sayfa HTML'inden Platform Durumu metnini çıkarır.
    Sayfada birden fazla 'işlem görüyor/görmüyor' geçebilir (i18n tablosu, FAQ vs).
    Bu yüzden 'Platform Durumu' etiketinin HEMEN sonrasındaki değeri ararız.
    """
    import html as html_mod

    # Yöntem 1: Embedded JSON içinde "platformDurum" alanı (en güvenilir)
    json_match = re.search(r'"platformDurum(u|)"\s*:\s*"([^"]+)"', html)
    if json_match:
        text = html_mod.unescape(json_match.group(2))
        return text

    # Yöntem 2: "Platform Durumu" etiketini bul, sonrasındaki durum metnini al
    # Sayfada iki "Platform Durumu" olabilir (BEFAS + TEFAS). TEFAS'a öncelik ver.
    # Formatlar: "TEFAS'ta işlem görüyor", "Fon Alımına Kapalı, Fon Bozumuna Açık" vs.
    platform_labels = list(re.finditer(r'Platform\s*Durumu', html, re.IGNORECASE))
    
    # Desen 2a: Standart TEFAS/BEFAS işlem durumu
    status_tefas_befas = (
        r"(TEFAS|BEFAS)(&#x27;|')ta\s+[İi\u0130][ş\u015F]lem"
        r"\s+(G[ö\u00F6]r[ü\u00FC]yor|G[ö\u00F6]rm[ü\u00FC]yor)"
    )
    # Desen 2b: Genel fallback — HTML'i temizle, | ile böl, ilk anlamlı metni al
    def _extract_first_text(after_html: str) -> str | None:
        chunk = after_html[:500]
        chunk = re.sub(r'<script[^>]*>.*?</script>', '', chunk, flags=re.DOTALL)
        chunk = re.sub(r'<style[^>]*>.*?</style>', '', chunk, flags=re.DOTALL)
        chunk = re.sub(r'<[^>]+>', '|', chunk)
        chunk = html_mod.unescape(chunk)
        segments = [s.strip() for s in chunk.split('|') if s.strip()]
        for seg in segments:
            # Geçerli metin: 8+ karakter, JSON/JS değil, sadece sayı değil,
            # "Platform Durumu" etiketinin kendisi değil
            if (len(seg) >= 8
                    and not re.search(r'[{}()\[\];:\\"]', seg)
                    and not re.match(r'^[\d\s/.]+$', seg)
                    and not re.match(r'^Platform\s*Durumu\s*:?\s*$', seg, re.IGNORECASE)):
                return re.sub(r'\s+', ' ', seg)
        return None

    for label_match in platform_labels:
        after_label = html[label_match.end():label_match.end() + 2000]
        # Önce TEFAS/BEFAS dene
        status_match = re.search(status_tefas_befas, after_label, re.IGNORECASE)
        if status_match:
            text = html_mod.unescape(status_match.group(0).strip())
            if "TEFAS" in text:
                return text
            continue  # BEFAS ise sonraki etikete bak (belki TEFAS'tır)

        # TEFAS/BEFAS yoksa genel fallback
        fallback = _extract_first_text(after_label)
        if fallback:
            return fallback

    # Hiçbir etiket TEFAS vermediyse, ilk BEFAS'ı veya genel fallback'i döndür
    for label_match in platform_labels:
        after_label = html[label_match.end():label_match.end() + 2000]
        status_match = re.search(status_tefas_befas, after_label, re.IGNORECASE)
        if status_match:
            return html_mod.unescape(status_match.group(0).strip())
        fallback = _extract_first_text(after_label)
        if fallback:
            return fallback

    # Yöntem 3: Son çare — tüm sayfada ara ama i18n tablosundan uzak dur
    # i18n JSON'u genelde sayfanın sonlarındadır. İlk 100KB içinde ara.
    search_region = html[:100000] if len(html) > 100000 else html
    patterns = [
        r"TEFAS'ta\s+işlem\s+(görüyor|görmüyor)",
        r"BEFAS'ta\s+işlem\s+(görüyor|görmüyor)",
        r"TEFAS&#x27;ta\s+[İi\u0130]şlem\s+(Görüyor|Görmüyor)",
        r"BEFAS&#x27;ta\s+[İi\u0130]şlem\s+(Görüyor|Görmüyor)",
    ]
    for pattern in patterns:
        match = re.search(pattern, search_region, re.IGNORECASE)
        if match:
            return html_mod.unescape(match.group(0).strip())

    return "HATA: Platform durumu parse edilemedi"


def create_scraper() -> cloudscraper.CloudScraper:
    """cloudscraper instance oluşturur, TEFAS cookie'lerini set eder."""
    scraper = cloudscraper.create_scraper(
        browser={
            'custom': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        },
    )
    # TEFAS'ın istediği device ID cookie'si
    scraper.cookies.set("tefas.clientDeviceId", DEVICE_ID)
    return scraper


def check_fund(scraper: cloudscraper.CloudScraper, fon_kodu: str) -> dict:
    """
    Tek bir fonun platform durumunu kontrol eder.
    Dönüş: {"platform_durumu": "...", "son_kontrol": "..."}
    """
    url = f"https://www.tefas.gov.tr/tr/fon-detayli-analiz/{fon_kodu}"
    headers = {
        "Authorization": TOKEN,
        "Referer": "https://www.tefas.gov.tr/tr/fon-verileri?fundType=YAT",
    }

    result = {"son_kontrol": datetime.now().isoformat(timespec="seconds")}

    try:
        r = scraper.get(url, headers=headers, timeout=30)

        if r.status_code != 200:
            result["platform_durumu"] = f"HATA: HTTP {r.status_code}"
            return result

        html = r.text

        # WAF kontrolü
        if "Request Rejected" in html:
            result["platform_durumu"] = "HATA: WAF engeli (Request Rejected)"
            return result

        if len(html) < 1000:
            result["platform_durumu"] = f"HATA: Sayfa çok kısa ({len(html)} bytes)"
            return result

        # Not: "bobcmn" F5 güvenlik script'i her gerçek sayfada da bulunur,
        # sadece "TEFAS" içeriği yoksa challenge sayfasıdır.
        if "TEFAS" not in html and "BEFAS" not in html:
            result["platform_durumu"] = "HATA: Challenge aşılamadı (içerik yok)"
            return result

        durum = parse_platform_durumu(html)
        result["platform_durumu"] = durum
        return result

    except Exception as e:
        result["platform_durumu"] = f"HATA: {type(e).__name__}: {str(e)[:100]}"
        return result


# ─── Ana Akış ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TEFAS Platform Durumu Çekici")
    parser.add_argument("--fund-type", type=str, default="YAT", choices=["YAT", "EMK"],
                        help="Fon tipi (varsayılan: YAT)")
    parser.add_argument("--update", action="store_true",
                        help="Sadece platform_status.json'da olmayan fonları çek")
    parser.add_argument("--resume", action="store_true",
                        help="HATA durumundaki + eksik fonları tekrar dene")
    parser.add_argument("--limit", type=int, default=None,
                        help="Test için maksimum fon sayısı")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Fonlar arası bekleme süresi, saniye (varsayılan: 0.5)")
    parser.add_argument("--save-interval", type=int, default=20,
                        help="Kaç fonda bir ara kayıt yapılsın (varsayılan: 20)")

    args = parser.parse_args()

    # Mevcut durumu yükle
    status = load_existing_status(args.fund_type)
    existing_codes = {
        k for k, v in status.items()
        if not k.startswith("_") and not str(v.get("platform_durumu", "")).startswith("HATA")
    }
    error_codes = {
        k for k, v in status.items()
        if not k.startswith("_") and str(v.get("platform_durumu", "")).startswith("HATA")
    }

    # Tüm fon kodlarını topla
    all_funds = collect_fund_codes(args.fund_type)
    if not all_funds:
        print("[HATA] Hiç fon bulunamadı.")
        return

    # Hangi fonlar kontrol edilecek?
    if args.resume:
        to_check = [(k, v) for k, v in all_funds if k not in existing_codes]
        print(f"[RESUME] {len(all_funds)} fondan {len(to_check)} eksik + {len(error_codes)} hatalı kontrol edilecek.")
    elif args.update:
        to_check = [(k, v) for k, v in all_funds if k not in existing_codes and k not in error_codes]
        print(f"[UPDATE] {len(all_funds)} fondan {len(to_check)} yeni/eksik fon kontrol edilecek.")
    else:
        # Tam çekim: mevcut dosya varsa silmek için sor
        if status and not args.limit:
            existing_count = len([k for k in status if not k.startswith("_")])
            meta = status.get("_meta", {})
            last_update = meta.get("son_guncelleme", "bilinmiyor")
            print(f"\n[!] Mevcut platform_status.json bulundu: {existing_count} fon")
            print(f"    Son güncelleme: {last_update}")
            choice = input("\nTam çekim yapmadan önce mevcut dosya SİLİNSİN mi? (E/h): ").strip().lower()
            if choice in ("e", "evet", "yes", ""):
                print("[OK] Mevcut dosya siliniyor, tüm fonlar yeniden çekilecek.")
                status = {}
                get_status_file(args.fund_type).unlink(missing_ok=True)
            else:
                print("[OK] Mevcut dosya korunuyor. Yeni sonuçlar üzerine yazılacak.")
        to_check = all_funds
        print(f"\n[FULL] {len(all_funds)} fonun tamamı kontrol edilecek.")

    if args.limit:
        to_check = to_check[:args.limit]
        print(f"[LIMIT] Sadece ilk {args.limit} fon kontrol edilecek.")

    if not to_check:
        print("[OK] Kontrol edilecek fon yok. Her şey güncel.")
        return

    # Cloudscraper başlat
    print("\n[*] Cloudscraper başlatılıyor...")
    scraper = create_scraper()
    print("[OK] Hazır.\n")

    success_count = 0
    error_count = 0
    islem_goren_count = 0
    islem_gormeyen_count = 0
    total = len(to_check)

    t_start = time.time()

    try:
        for i, (fon_kodu, fon_adi) in enumerate(to_check, 1):
            print(f"[{i}/{total}] {fon_kodu}: {fon_adi[:60]} ... ", end="", flush=True)

            result = check_fund(scraper, fon_kodu)
            durum = result["platform_durumu"]

            status[fon_kodu] = {
                "fon_adi": fon_adi,
                "platform_durumu": durum,
                "fund_type": args.fund_type,
                "son_kontrol": result["son_kontrol"],
            }

            if durum.startswith("HATA"):
                print(f"HATA: {durum}")
                error_count += 1
            else:
                print(f"✓ {durum}")
                success_count += 1
                durum_norm = _turkish_normalize(durum)
                if "işlem görüyor" in durum_norm and "görmüyor" not in durum_norm:
                    islem_goren_count += 1
                elif "işlem görmüyor" in durum_norm:
                    islem_gormeyen_count += 1

            # Periyodik kayıt
            if i % args.save_interval == 0:
                save_status(status, args.fund_type)
                elapsed = time.time() - t_start
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                print(f"  [KAYIT] Ara kayıt ({i}/{total}). "
                      f"Hız: {rate:.1f} fon/sn, "
                      f"İşlem gören: {islem_goren_count}, "
                      f"Görmeyen: {islem_gormeyen_count}, "
                      f"Hata: {error_count}, "
                      f"ETA: {eta/60:.0f} dk")

            # Rate limiting
            if i < total:
                time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n[IPTAL] Kullanıcı tarafından durduruldu. İlerleme kaydediliyor...")
    finally:
        save_status(status, args.fund_type)

    # Özet
    elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    print("  TAMAMLANDI")
    print("=" * 60)
    print(f"  Başarılı:        {success_count}")
    print(f"  - İşlem görüyor:  {islem_goren_count}")
    print(f"  - İşlem görmüyor: {islem_gormeyen_count}")
    print(f"  Hatalı:          {error_count}")
    print(f"  Toplam:          {total}")
    print(f"  Süre:            {elapsed/60:.1f} dk")
    print(f"  Kayıt:           {get_status_file(args.fund_type)}")
    print("=" * 60)


if __name__ == "__main__":
    main()


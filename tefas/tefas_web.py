"""TEFAS web sitesinden fon detay bilgisi çeken modül.

Önce `cloudscraper` (WAF aşmak için, eğer kuruluysa) ile dener,
sonra `urllib.request` (stdlib) ile fallback yapar.
Hata durumunda (bağlantı kesikliği, banlama vb.) None döner ve dashboard
sessizce devam eder.
"""
from __future__ import annotations

import html as _html_mod
import re
import time
from typing import Any
import urllib.request
import urllib.error


_BASE = "https://www.tefas.gov.tr/tr/fon-detayli-analiz"

# Son hata mesajı (dashboard'da gösterilmek üzere)
_LAST_ERROR: str = ""

# TEFAS API kimlik bilgileri (download_tefas.py / fetch_platform_status.py ile aynı)
_AUTH_TOKEN = "Bearer ST-tefaswebwse3irfmSBj4iRAzGPbAlS94Se"
_DEVICE_ID = "a700557e-4bdd-4fc1-abb1-b941c352a7fc.FnRVcGVTWbT_cnZgITo3EGtVPiv6Zle1HVw9yd8erQ0"

# cloudscraper için sadece Authorization + Referer yeterli;
# diğer başlıkları (User-Agent, sec-ch-ua vb.) cloudscraper kendisi ekler.
_CLOUDSCRAPER_HEADERS = {
    "Authorization": _AUTH_TOKEN,
    "Referer": "https://www.tefas.gov.tr/tr/fon-verileri?fundType=YAT",
}

# urllib fallback için tam header seti
_URLLIB_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "tr,en;q=0.9",
    "Authorization": _AUTH_TOKEN,
    "Connection": "keep-alive",
    "Referer": "https://www.tefas.gov.tr/tr/fon-verileri?fundType=YAT",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Upgrade-Insecure-Requests": "1",
}


# Lazy-initialized cloudscraper singleton (fetch_platform_status.py ile aynı pattern)
_SCRAPER: Any = None
_SCRAPER_ERROR: str | None = None


def _get_scraper() -> Any | None:
    """Cloudscraper instance'ını lazy olarak oluşturur, tekrar tekrar create etmez."""
    global _SCRAPER, _SCRAPER_ERROR
    if _SCRAPER is not None:
        return _SCRAPER
    if _SCRAPER_ERROR is not None:
        return None
    try:
        import cloudscraper
        _SCRAPER = cloudscraper.create_scraper(
            browser={
                "custom": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36"
            },
        )
        _SCRAPER.cookies.set("tefas.clientDeviceId", _DEVICE_ID)
        return _SCRAPER
    except ImportError:
        _SCRAPER_ERROR = "cloudscraper kurulu değil"
    except Exception as e:
        _SCRAPER_ERROR = f"cloudscraper oluşturulamadı: {type(e).__name__}: {e}"
    return None


def get_last_error() -> str:
    """Son başarısız _fetch_html çağrısının hata mesajını döndürür."""
    return _LAST_ERROR


def _fetch_html(code: str, timeout: int = 30) -> str | None:
    """Fon detay sayfasının HTML'ini çeker.

    Önce cloudscraper + Authorization token ile dener (WAF aşmak için),
    yoksa urllib'e düşer.
    """
    global _LAST_ERROR
    url = f"{_BASE}/{code.upper()}"
    errors: list[str] = []

    # 1. cloudscraper + Authorization token (F5 Shape Security WAF aşmak için)
    scraper = _get_scraper()
    if scraper is not None:
        try:
            resp = scraper.get(url, headers=_CLOUDSCRAPER_HEADERS, timeout=timeout)
            if resp.status_code != 200:
                errors.append(f"cloudscraper HTTP {resp.status_code}")
            elif len(resp.text) <= 1000:
                errors.append(f"cloudscraper: sayfa çok kısa ({len(resp.text)} bytes)")
            elif "Request Rejected" in resp.text:
                errors.append("cloudscraper: WAF 'Request Rejected' yanıtı")
            elif "TEFAS" not in resp.text and "BEFAS" not in resp.text:
                errors.append("cloudscraper: challenge sayfası (TEFAS/BEFAS içeriği yok)")
            else:
                return resp.text
        except Exception as e:
            errors.append(f"cloudscraper istek hatası: {type(e).__name__}: {e}")
    else:
        errors.append(_SCRAPER_ERROR or "cloudscraper kullanılamadı")

    # 2. Fallback: urllib (cloudscraper yoksa veya başarısızsa)
    req = urllib.request.Request(url, headers=_URLLIB_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            if len(html) <= 1000:
                errors.append(f"urllib: sayfa çok kısa ({len(html)} bytes)")
            elif "Request Rejected" in html:
                errors.append("urllib: WAF 'Request Rejected' yanıtı")
            elif "TEFAS" not in html and "BEFAS" not in html:
                errors.append("urllib: challenge sayfası (TEFAS/BEFAS içeriği yok)")
            else:
                return html
    except urllib.error.HTTPError as e:
        errors.append(f"urllib HTTP {e.code} ({e.reason})")
    except urllib.error.URLError as e:
        errors.append(f"urllib bağlantı hatası: {e.reason}")
    except Exception as e:
        errors.append(f"urllib: {type(e).__name__}: {e}")

    _LAST_ERROR = " | ".join(errors) if errors else "bilinmeyen hata"
    return None


def _strip_tags(raw: str) -> str:
    """Ham HTML'den etiketleri soyar, boşlukları temizler."""
    text = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(text.split())


def _between(html: str, start: str, end: str) -> str | None:
    """html içinde start ve end arasındaki ilk metni döndürür (tag-stripped)."""
    i = html.find(start)
    if i == -1:
        return None
    j = html.find(end, i + len(start))
    if j == -1:
        return None
    return _strip_tags(html[i + len(start):j]).strip() or None


# TEFAS Next.js sayfasındaki etiket-değer çiftlerini bulan regex.
# Yapı: <p class="...text-primary-muted">ETİKET</p><p class="...font-bold text-content-primary">DEĞER</p>
_LABEL_VALUE_RE = re.compile(
    r'(?:<p[^>]*text-primary-muted[^>]*>|<span[^>]*text-primary-muted[^>]*>)'
    r'(.*?)'
    r'(?:</p>|</span>)'
    r'\s*(?:<[^>]*>)*?\s*'
    r'<p[^>]*font-bold text-content-primary[^>]*>'
    r'(.*?)'
    r'</p>',
    re.DOTALL,
)


def _parse_all_label_value_pairs(html: str) -> dict[str, str]:
    """Tüm etiket-değer çiftlerini tek bir regex taramasıyla ayrıştırır.

    Yeni TEFAS Next.js sayfa yapısına göre:
    - Etiket: <p class="...text-primary-muted"> veya <span ...text-primary-muted">
    - Değer:  <p class="...font-bold text-content-primary">

    Döndürülen sözlükte anahtarlar HTML entity'leri çözülmüş etiket metni,
    değerler ise entity çözülmüş değer metnidir.
    """
    result: dict[str, str] = {}
    seen: set[str] = set()
    for label_raw, value_raw in _LABEL_VALUE_RE.findall(html):
        label = _html_mod.unescape(_strip_tags(label_raw))
        value = _html_mod.unescape(_strip_tags(value_raw))
        if label and value and label not in seen:
            seen.add(label)
            result[label] = value
    return result


def fetch_fund_info(code: str) -> dict[str, Any] | None:
    """
    TEFAS sitesinden fon bilgilerini çeker ve temiz bir sözlük döndürür.

    Dönen sözlük anahtarları:
      fon_kodu, isin_kodu, platform_durumu, risk_degeri,
      alis_valoru, satis_valoru, is_baslama_saati, son_is_saati,
      giris_komisyonu, cikis_komisyonu,
      son_fiyat, gunluk_getiri, pay_adedi, toplam_deger,
      kategorisi, kategori_derecesi, yatirimci_sayisi, pazar_payi,
      getiri_1ay, getiri_3ay, getiri_6ay, getiri_1yil,
      varlik_dagilimi   (list of {varlik, oran})

    Hata / bağlantı sorunu durumunda None döner.
    """
    html = _fetch_html(code)
    if not html:
        return None

    info: dict[str, Any] = {"fon_kodu": code.upper()}

    # Tüm etiket-değer çiftlerini tek seferde ayrıştır
    pairs = _parse_all_label_value_pairs(html)

    # Bazı etiketler HTML yapısı gereği section başlığı ile birleşebilir
    # (örn. "Getiri Bilgisi Son 1 Ay Getirisi"). substring fallback ile bul.
    def _lookup(key: str, default: str = "-") -> str:
        if key in pairs:
            return pairs[key]
        # Substring fallback: anahtarın son kısmı eşleşen pair'i bul
        for k, v in pairs.items():
            if k.endswith(key):
                return v
        return default

    # ── Kimlik bilgileri ──────────────────────────────────────────────────────
    info["isin_kodu"] = pairs.get("ISIN Kodu", "-")
    info["platform_durumu"] = pairs.get("Platform Durumu", "-")
    info["risk_degeri"] = pairs.get("Fon Risk Değeri", "-")
    info["is_baslama_saati"] = pairs.get("İşlem Başlama Saati", "-")
    info["son_is_saati"] = pairs.get("Son İşlem Saati", "-")
    info["alis_valoru"] = pairs.get("Fon Alış Valörü", "-")
    info["satis_valoru"] = pairs.get("Fon Satış Valörü", "-")
    info["min_alis"] = pairs.get("Min. Alış İşlem Miktarı", "-")
    info["min_satis"] = pairs.get("Min. Satış İşlem Miktarı", "-")
    info["giris_komisyonu"] = pairs.get("Giriş Komisyonu", "-")
    info["cikis_komisyonu"] = pairs.get("Çıkış Komisyonu", "-")

    # ── Fon Bilgisi metrikleri ───────────────────────────────────────────────
    info["son_fiyat"] = pairs.get("Son Fiyat (TL)", "-")
    info["gunluk_getiri"] = pairs.get("Günlük Getiri (%)", "-")
    info["pay_adedi"] = pairs.get("Pay (Adet)", "-")
    info["toplam_deger"] = pairs.get("Fon Toplam Değer (TL)", "-")
    info["kategorisi"] = pairs.get("Kategorisi", "-")
    info["kategori_derecesi"] = pairs.get("Son 1 Yıllık Kategori Derecesi", "-")
    info["yatirimci_sayisi"] = pairs.get("Yatırımcı Sayısı", "-")
    info["pazar_payi"] = pairs.get("Pazar Payı", "-")

    # ── Getiri Bilgisi ───────────────────────────────────────────────────────
    info["getiri_1ay"] = _lookup("Son 1 Ay Getirisi")
    info["getiri_3ay"] = _lookup("Son 3 Ay Getirisi")
    info["getiri_6ay"] = _lookup("Son 6 Ay Getirisi")
    info["getiri_1yil"] = _lookup("Son 1 Yıl Getirisi")

    # ── Varlık Dağılımı tablosu ──────────────────────────────────────────────
    varlik: list[dict] = []
    # "Fon Varlık Dağılımı" bölümünü bul — h3 başlığını hedefle,
    # çünkü sayfa içindeki buton/aria-label'ler de aynı metni içerir.
    vd_header = re.search(
        r'<h3[^>]*>[^<]*Fon Varl[^<]*</h3>', html, re.DOTALL
    )
    if vd_header:
        vd_start = vd_header.end()
        # Bir sonraki h3 başlığına (Getiri Bilgisi) kadar olan kısmı al
        vd_end_match = re.search(r'<h3[^>]*>', html[vd_start:])
        vd_end = vd_start + vd_end_match.start() if vd_end_match else vd_start + 5000
        vd_block = html[vd_start:vd_end]
        # <tr> satırlarını bul
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", vd_block, re.DOTALL)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) >= 2:
                varlik_turu = _strip_tags(cells[0]).strip()
                oran = _strip_tags(cells[1]).strip()
                if varlik_turu and oran and varlik_turu not in ("Varlık Türü", ""):
                    varlik.append({"Varlık Türü": varlik_turu, "Oran": oran})

    info["varlik_dagilimi"] = varlik

    # ── KAP sayfası linki ────────────────────────────────────────────────────
    # TEFAS Next.js sayfasında KAP linki JSON verisi içinde "kapLink" olarak gelir.
    # JSON escape edilmiş olabilir: "kapLink" veya \"kapLink\"
    kap_match = re.search(
        r'\\?"kapLink\\?"\s*:\s*\\?"(https?://[^"\\]*kap\.org\.tr[^"\\]*)\\?"',
        html, re.IGNORECASE,
    )
    if not kap_match:
        # Eski HTML yapısı: href içinde arama (fallback)
        kap_match = re.search(
            r'href="(https?://[^"]*kap\.org\.tr[^"]*)"', html, re.IGNORECASE
        )
    info["kap_url"] = kap_match.group(1) if kap_match else None

    return info

# Plan: TEFAS Web Entegrasyonu — Fon Detay Sayfasına Canlı Veri Getirme

## Amaç

[`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) sayfasına "TEFAS'tan Bilgi Getir" butonu ekleyerek, seçili fonun TEFAS web sitesindeki (`https://www.tefas.gov.tr/tr/fon-detayli-analiz/{KOD}`) güncel detay bilgilerini çekip göstermek.

Bu sistemde **olmayan** veriler: ISIN kodu, platform durumu, risk değeri, işlem saatleri, valör, komisyon, kategori, kategori derecesi, yatırımcı sayısı, pazar payı, varlık dağılımı, KAP linki.

## Mevcut Durum

| Dosya | Durum |
|---|---|
| [`tefas/tefas_web.py`](../tefas/tefas_web.py) | **Tamamlanmış** — HTML scraping mantığı hazır, `fetch_fund_info(code)` fonksiyonu tüm alanları parse ediyor. Ancak **hiçbir yerden import edilmiyor** ve WAF dayanıklılığı yok (sadece `urllib.request`). |
| [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | Fon detay sayfası hazır, ancak TEFAS web entegrasyonu yok. |
| [`GetDataSet/fetch_platform_status.py`](../GetDataSet/fetch_platform_status.py) | `cloudscraper` ile WAF aşarak platform durumu çekiyor — referans implementasyon. |

## Mimari

```
Kullanıcı butona tıklar
        │
        ▼
st.session_state kontrolü (cache)
        │
        ├── Cache'de varsa → doğrudan göster
        │
        └── Cache'de yoksa:
                │
                ▼
        tefas_web.fetch_fund_info(code)
                │
                ├── cloudscraper varsa → onunla dene
                └── yoksa → urllib.request ile dene
                        │
                        ▼
                HTML parse (regex)
                        │
                        ▼
                Dict döndür
                        │
                        ▼
                session_state'e kaydet
                        │
                        ▼
                UI'de göster
```

## Değişiklik Yapılacak Dosyalar

### 1. [`tefas/tefas_web.py`](../tefas/tefas_web.py) — WAF Dayanıklılığı Ekle

**Mevcut problem**: Sadece `urllib.request` kullanıyor. TEFAS'ta F5 Shape Security WAF var, `urllib.request` çoğu zaman `403` veya challenge sayfası dönebilir.

**Yapılacak**: `_fetch_html()` fonksiyonuna iki-kademeli yaklaşım ekle:

```python
def _fetch_html(code: str, timeout: int = 10) -> str | None:
    """Fon detay sayfasının HTML'ini çeker.
    
    Önce cloudscraper dener (WAF aşmak için), yoksa urllib'e düşer.
    """
    url = f"{_BASE}/{code.upper()}"
    
    # 1. cloudscraper (WAF aşar)
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={'custom': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        scraper.cookies.set("tefas.clientDeviceId", 
            "a700557e-4bdd-4fc1-abb1-b941c352a7fc.FnRVcGVTWbT_cnZgITo3EGtVPiv6Zle1HVw9yd8erQ0")
        resp = scraper.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp.text
    except Exception:
        pass
    
    # 2. Fallback: urllib (cloudscraper yoksa veya başarısızsa)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            if len(html) > 1000:
                return html
    except Exception:
        pass
    
    return None
```

Ayrıca `_HEADERS` sözlüğüne `Referer` ekle:
```python
_HEADERS = {
    ...
    "Referer": "https://www.tefas.gov.tr/tr/fon-verileri?fundType=YAT",
}
```

**Cloudscraper bağımlılığı**: Zaten `pyproject.toml`'da `fetch` opsiyonel bağımlılığı olarak tanımlı. Dashboard kullanıcısına `pip install -e .[fetch]` yapması gerektiği hatırlatılabilir (dashboard çalışmaya devam eder, sadece urllib ile dener).

**Ek kontrol**: `_fetch_html` dönüşünde WAF challenge kontrolü:
```python
if html and "Request Rejected" not in html and "TEFAS" in html:
    return html
```

---

### 2. [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) — Buton + UI Entegrasyonu

#### 2a. Import Ekle (en üste, diğer import'ların yanına)

```python
from tefas import tefas_web
```

#### 2b. Buton ve Fetch Mantığı (mevcut metrik kartlarından **önce**, `st.info` satırından hemen sonra — yani ~line 44'ten sonra)

```python
# ── TEFAS Web Entegrasyonu ─────────────────────────────────────────────────
CACHE_KEY = f"tefas_web_{code}"

if st.button("🔍 TEFAS'tan Bilgi Getir", key=f"btn_tefas_{code}"):
    with st.spinner(f"TEFAS'tan {code} bilgileri çekiliyor..."):
        web_info = tefas_web.fetch_fund_info(code)
        if web_info is None:
            st.warning("⚠️ TEFAS'a bağlanılamadı. İnternet bağlantınızı kontrol edin veya daha sonra tekrar deneyin.")
            st.session_state[CACHE_KEY] = None
        else:
            st.session_state[CACHE_KEY] = web_info
            st.success(f"✅ {code} bilgileri TEFAS'tan getirildi.")
```

#### 2c. Veri Gösterimi (butondan hemen sonra, session_state kontrolü ile)

Eğer `st.session_state.get(CACHE_KEY)` doluysa, aşağıdaki UI bölümlerini render et:

```python
web_info = st.session_state.get(CACHE_KEY)
if web_info:
    st.divider()
    st.subheader(f"📡 TEFAS Canlı Veri — {code}")
    
    # ── Kimlik Bilgileri ──────────────────────────────────────────────────
    st.caption("Kimlik Bilgileri")
    kcols = st.columns(4)
    kcols[0].metric("ISIN Kodu", web_info.get("isin_kodu", "-"))
    
    # Platform Durumu — renkli göster
    pdurum = web_info.get("platform_durumu", "-")
    pdurum_norm = pdurum.replace("İ", "i").replace("ı", "i").lower()
    if "işlem görüyor" in pdurum_norm and "görmüyor" not in pdurum_norm:
        kcols[1].metric("Platform Durumu", "✅ " + pdurum)
    elif "görmüyor" in pdurum_norm:
        kcols[1].metric("Platform Durumu", "❌ " + pdurum)
    else:
        kcols[1].metric("Platform Durumu", pdurum)
    
    kcols[2].metric("Risk Değeri", web_info.get("risk_degeri", "-"))
    kcols[3].metric("Kategorisi", web_info.get("kategorisi", "-"))
    
    # ── İşlem Bilgileri ───────────────────────────────────────────────────
    st.caption("İşlem Bilgileri")
    icols = st.columns(5)
    icols[0].metric("Alış Valörü", web_info.get("alis_valoru", "-"))
    icols[1].metric("Satış Valörü", web_info.get("satis_valoru", "-"))
    icols[2].metric("Giriş Komisyonu", web_info.get("giris_komisyonu", "-"))
    icols[3].metric("Çıkış Komisyonu", web_info.get("cikis_komisyonu", "-"))
    icols[4].metric("Kategori Derecesi", web_info.get("kategori_derecesi", "-"))
    
    icols2 = st.columns(4)
    icols2[0].metric("İşlem Başlama", web_info.get("is_baslama_saati", "-"))
    icols2[1].metric("Son İşlem", web_info.get("son_is_saati", "-"))
    icols2[2].metric("Min Alış Miktarı", web_info.get("min_alis", "-"))
    icols2[3].metric("Min Satış Miktarı", web_info.get("min_satis", "-"))
    
    # ── Fon İstatistikleri ────────────────────────────────────────────────
    st.caption("Fon İstatistikleri")
    fcols = st.columns(5)
    fcols[0].metric("Son Fiyat (TL)", web_info.get("son_fiyat", "-"))
    fcols[1].metric("Günlük Getiri", web_info.get("gunluk_getiri", "-"))
    fcols[2].metric("Pay Adedi", web_info.get("pay_adedi", "-"))
    fcols[3].metric("Yatırımcı Sayısı", web_info.get("yatirimci_sayisi", "-"))
    fcols[4].metric("Pazar Payı", web_info.get("pazar_payi", "-"))
    
    # ── Varlık Dağılımı ───────────────────────────────────────────────────
    varlik = web_info.get("varlik_dagilimi", [])
    if varlik:
        st.caption("Varlık Dağılımı")
        import pandas as pd
        vdf = pd.DataFrame(varlik)
        # Streamlit dataframe (veya bar chart)
        st.dataframe(vdf, width="stretch", hide_index=True)
        
        # Alternatif: Yatay bar chart
        try:
            import plotly.express as px
            vdf_clean = vdf.copy()
            vdf_clean["Oran_num"] = pd.to_numeric(
                vdf_clean["Oran"].str.replace("%", "").str.replace(",", "."), 
                errors="coerce"
            )
            fig_v = px.bar(
                vdf_clean.dropna(subset=["Oran_num"]).sort_values("Oran_num"),
                x="Oran_num", y="Varlık Türü", orientation="h",
                title="Fon Varlık Dağılımı (%)",
                color="Oran_num", color_continuous_scale="Blues"
            )
            fig_v.update_layout(height=max(200, 30 * len(vdf_clean) + 60), margin=dict(t=40, b=10))
            st.plotly_chart(fig_v, width="stretch")
        except Exception:
            pass  # bar chart başarısız olursa dataframe yeterli
    
    # ── KAP Linki ─────────────────────────────────────────────────────────
    kap_url = web_info.get("kap_url")
    if kap_url:
        st.caption("📄 KAP")
        st.link_button("🔗 KAP Sayfasını Aç", kap_url)
    
    # ── Ham Veri (expander içinde) ────────────────────────────────────────
    with st.expander("Ham TEFAS Verisi"):
        st.json(web_info)
```

---

### 3. Test Dosyası (yeni) — `tests/test_tefas_web.py`

```python
"""tefas_web modülü için birim testleri."""
import pytest
from tefas import tefas_web


SAMPLE_HTML = """
<html>
<body>
<div>ISIN Kodu</div><span>TRYFNG00001</span>
<div>Platform Durumu</div><span>TEFAS'ta işlem görüyor</span>
<div>Fon Risk Değeri</div><span>5</span>
<div>Son Fiyat (TL)</div><span>12.345678</span>
<div>Günlük Getiri (%)</div><span>%0.52</span>
<div>Kategorisi</div><span>Hisse Senedi</div>
<div>Son 1 Yıllık Kategori Derecesi</div><span>3 / 45</span>
<div>Yatırımcı Sayısı</div><span>12,345</span>
<div>Pazar Payı</div><span>%2.5</span>
<div>Son 1 Ay Getirisi</div><span>%3.21</span>
</body>
</html>
"""


class TestStripTags:
    def test_removes_tags(self):
        assert tefas_web._strip_tags("<div>Hello</div>") == "Hello"
    
    def test_collapses_whitespace(self):
        assert tefas_web._strip_tags("<p>a   b</p>") == "a b"


class TestBetween:
    def test_extracts_text_between_markers(self):
        result = tefas_web._between("<div>A</div><span>X</span>", "<div>A</div>", "</span>")
        assert result == "X"
    
    def test_returns_none_if_start_not_found(self):
        assert tefas_web._between("abc", "NOT_THERE", "end") is None


class TestParseLabelValuePairs:
    def test_extracts_known_labels(self):
        labels = ["ISIN Kodu", "Fon Risk Değeri"]
        result = tefas_web._parse_label_value_pairs(SAMPLE_HTML, labels)
        assert result.get("ISIN Kodu") == "TRYFNG00001"
        assert result.get("Fon Risk Değeri") == "5"


class TestFetchFundInfo:
    def test_returns_none_for_invalid_code(self, monkeypatch):
        def mock_fetch(code, timeout=10):
            return None
        monkeypatch.setattr(tefas_web, "_fetch_html", mock_fetch)
        assert tefas_web.fetch_fund_info("INVALID") is None
```

---

## Adım Adım Uygulama Sırası

| # | Adım | Dosya | Açıklama |
|---|---|---|---|
| 1 | WAF dayanıklılığı ekle | [`tefas/tefas_web.py`](../tefas/tefas_web.py) | `_fetch_html`'e cloudscraper fallback + WAF challenge kontrolü |
| 2 | `_HEADERS`'a `Referer` ekle | [`tefas/tefas_web.py`](../tefas/tefas_web.py) | TEFAS origin kontrolünden geçmek için |
| 3 | Import ekle | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | `from tefas import tefas_web` |
| 4 | Buton + spinner + fetch | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | `st.button` → `tefas_web.fetch_fund_info(code)` → `st.session_state` |
| 5 | Kimlik bilgileri kartları | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | ISIN, Platform Durumu (renkli), Risk Değeri, Kategori |
| 6 | İşlem bilgileri kartları | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | Valör, komisyon, işlem saatleri, min işlem miktarı |
| 7 | Fon istatistikleri kartları | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | Son fiyat, günlük getiri, pay adedi, yatırımcı sayısı, pazar payı |
| 8 | Varlık dağılımı tablosu + bar chart | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | `st.dataframe` + `px.bar` yatay bar |
| 9 | KAP link butonu | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | `st.link_button` |
| 10 | Ham veri expander'ı | [`tefas/dashboard/views/fon_detay.py`](../tefas/dashboard/views/fon_detay.py) | `st.json(web_info)` |
| 11 | Test dosyası oluştur | [`tests/test_tefas_web.py`](../tests/test_tefas_web.py) | `_strip_tags`, `_between`, `_parse_label_value_pairs`, `fetch_fund_info` |
| 12 | Uçtan uca test | Manuel | `tefas dashboard` → Fon Detay → BIH seç → butona tıkla |

## UI Yerleşimi (Fon Detay Sayfasındaki Sıralama)

```
1. Sidebar: Fon tipi seçimi
2. st.title("Fon Detay")
3. st.selectbox("Fon seç")
4. st.caption (Fon Adı)
5. st.info (Rasyonel)
   ↓↓↓ YENİ BÖLÜM BURADA ↓↓↓
6. [BUTON] "🔍 TEFAS'tan Bilgi Getir"
7. [SESSION STATE KONTROLÜ]
   7a. Kimlik Bilgileri (4 sütun)
   7b. İşlem Bilgileri (5 + 4 sütun)
   7c. Fon İstatistikleri (5 sütun)
   7d. Varlık Dağılımı (tablo + bar chart)
   7e. KAP Linki
   7f. Ham Veri (expander)
   ↑↑↑ YENİ BÖLÜM BİTİŞİ ↑↑↑
8. [MEVCUT] Metrik kartları (Composite skor, Yıllık getiri, ...)
9. [MEVCUT] Tarih aralığı slider
10. [MEVCUT] Büyüme + Drawdown grafikleri
11. [MEVCUT] Rolling metrikler + Aylık getiri bar
12. [MEVCUT] Akran kıyas tablosu
13. [MEVCUT] Skor geçmişi
14. [MEVCUT] Tüm metrikler expander
```

## Hata Yönetimi Stratejisi

| Senaryo | Davranış |
|---|---|
| TEFAS'a bağlanılamadı (timeout/DNS) | `st.warning` → kullanıcıya "daha sonra tekrar deneyin" mesajı |
| WAF challenge aşılamadı (403 / Request Rejected) | `st.warning` → "TEFAS güvenlik duvarı aşılamadı, cloudscraper yüklemeyi deneyin: pip install cloudscraper" |
| HTML parse edildi ama bazı alanlar eksik | Eksik alanlar `-` (tire) olarak gösterilir |
| Varlık dağılımı boş | O bölüm hiç render edilmez |
| KAP linki yok | O bölüm hiç render edilmez |
| bar chart çizilemedi (veri tipi sorunu) | Sessizce atlanır, sadece dataframe gösterilir |

## Bağımlılıklar

- **Mevcut**: `streamlit>=1.35`, `plotly>=5.20` (dashboard), `pandas`
- **Opsiyonel (önerilen)**: `cloudscraper>=1.2` — `pip install -e .[fetch]` ile kurulur. Kurulu değilse `urllib.request` ile denenir (WAF nedeniyle başarısız olabilir).

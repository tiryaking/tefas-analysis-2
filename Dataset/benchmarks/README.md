# Benchmark Serileri (opsiyonel)

Bu klasöre konan günlük endeks/fiyat CSV'leri, fonlar için **Beta / Jensen
Alpha / Tracking Error / Information Ratio** hesaplanmasını etkinleştirir
(bkz. `tefas/benchmarks.py`). Klasör boşsa pipeline aynen çalışır; bu
metrikler NaN kalır.

## Dosya formatı

- Dosya adı = benchmark kimliği: `xu100.csv`, `altin.csv`, `usdtry.csv` …
- Kolonlar: `Tarih` (veya `Date`, ISO `YYYY-MM-DD` ya da `DD.MM.YYYY`) ve
  `Deger` (veya `Close`/`Value`). Türkçe ondalık (`1.234,56`) desteklenir.
- Günlük frekans; eksik günler sorun değil (fonla kesişen günler kullanılır).
- En az 60 gözlem gerekir (`MIN_RELATIVE_OBS`).

```csv
Tarih,Deger
2025-01-02,9875.43
2025-01-03,9910.12
```

## Tema → benchmark eşlemesi

`tefas/benchmarks.py::THEME_BENCHMARK`:

| Tema | Benchmark dosyası |
|---|---|
| Hisse Senedi, Teknoloji | `xu100.csv` (BIST 100) |
| Altın & Kıymetli Maden | `altin.csv` (gram altın TL) |
| Yabancı / Endeks | `usdtry.csv` (USD/TRY) |

Para Piyasası / Borçlanma gibi temalara piyasa betası anlamlı atfedilemediği
için eşleme yoktur; gerekirse `THEME_BENCHMARK`'a satır ekleyin.

## Otomatik indirme (önerilen)

`GetDataSet/download_benchmarks.py` bu klasörü TCMB EVDS API'sinden doldurur
(xu100, altin, usdtry + mevduat faizinden sentezlenen `mevduat.csv` endeksi):

```
# bir kez: https://evds2.tcmb.gov.tr üye ol, profildən API anahtarını al
set EVDS_API_KEY=...          # veya tefas.config.json'a "evds_api_key" ekle
python GetDataSet/download_benchmarks.py            # son 24 ay
python GetDataSet/download_benchmarks.py --update   # eksik günleri tamamla
```

`download_tefas.py --update` ile birlikte çalıştırmak iyi bir alışkanlıktır;
seriler fon verisinden 7+ gün geri kalırsa `tefas run` bilgilendirici bir
`[WARN]` basar (asla hata vermez). EVDS seri kodları script'in başındaki
`SERIES` tablosundadır — kod değişirse yalnızca orası güncellenir.

## Elle veri kaynakları (alternatif)

- BIST 100 (XU100): Borsa İstanbul / TCMB EVDS / investing.com dışa aktarımı
- Gram altın (TL) ve USD/TRY: TCMB EVDS (https://evds2.tcmb.gov.tr) günlük seriler

CSV'yi dışa aktarırken kolon adlarını yukarıdaki formata getirmeniz yeterlidir.

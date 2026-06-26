# Dataset Klasoru

Bu klasorde TEFAS API'dan indirilen aylik fon verileri bulunur.

## Veri Yapisi

Her CSV dosyasi bir aylik veriyi icerir. Dosya adi: `YYYY-MM-DD_YYYY-MM-DD.csv`

| Sutun | Aciklama |
|---|---|
| Fon Kodu | 3 haneli fon kodu (orn: AAS, THY) |
| Fon Adi | Fonun tam adi |
| Tarih | Islem tarihi |
| Fiyat | Birim fiyat (TL) |
| Tedavuldeki Pay Sayisi | Dolaşimdaki pay adedi |
| Kisi Sayisi | Yatirimci sayisi |
| Fon Toplam Deger | Fonun toplam portfoy degeri |

## Veri Indirme

Indirme scripti: `GetDataset/download_tefas.py`

```bash
# Son 1 yil (18 ay)
python GetDataset/download_tefas.py --start 2025-01-01

# Son 6 ay
python GetDataset/download_tefas.py --months 6

# Belirli tarih araligi
python GetDataset/download_tefas.py --start 2025-06-01 --months 12
```

## Pipeline

Dataset hazir olduktan sonra analiz icin:

```bash
python etl_pipeline.py [--filter "FILTRI"]
python financial_metrics.py [--filter "FILTRI"]
python generate_top10_report.py --top 5 [--filter "FILTRI"]
python generate_pdf_reportlab_pretty.py [--filter "FILTRI"]
```

## Notlar

- API max 1 aylik sorgulama destekler
- Rate limit var: istekler arasinda 3-5 sn bekleme gerekir
- 429 hatasi alinirsa bekleyip tekrar deneyin
- Mevcut dosyalar atlanir (tekrar indirilmez)
- Encoding: UTF-8-BOM (Excel uyumlu)

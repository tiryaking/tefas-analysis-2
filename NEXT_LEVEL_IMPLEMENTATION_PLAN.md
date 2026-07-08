# TEFAS Fon Tavsiye Uygulaması — Üst Seviye Uygulama Planı

## Amaç

Bu planın hedefi, mevcut TEFAS analiz aracını “en yüksek skorlu fon listesi” üreten bir araçtan, yatırımcı risk profiline göre açıklanabilir ve doğrulanabilir fon önerisi yapan bir karar destek sistemine taşımaktır.

Bu çalışma yatırım tavsiyesi iddiası taşımaz. Amaç, mevcut tarihsel TEFAS veri seti üzerinde çalışan kantitatif bir öneri ve raporlama sistemini daha anlaşılır, ölçülebilir ve ürünleşebilir hale getirmektir.

## Kapsam Dışı

Bu uygulama turunda yeni veri kaynağı entegrasyonu yapılmayacaktır.

Kapsam dışı işler:

- KAP sürekli bilgilendirme formu entegrasyonu
- TCMB EVDS entegrasyonu
- Yeni harici benchmark/veri sağlayıcı entegrasyonu
- Veritabanına geçiş
- REST API veya web servis üretimi
- Gerçek zamanlı veri akışı

Mevcut veri kaynakları kullanılacaktır:

- `Dataset/` altındaki TEFAS tarihsel fiyat/AUM verileri
- `Dataset/platform_status/` aktiflik verileri
- Varsa mevcut `Dataset/benchmarks/*.csv`
- `Output/*.parquet` ve mevcut backtest CSV çıktıları

## Ürün Hedefi

Sistem, kullanıcıya şu soruları cevaplayan bir öneri üretmelidir:

- Bu fon neden önerildi?
- Bu fon hangi riskleri taşıyor?
- Bu fon hangi yatırımcı profiline uygun?
- Alternatif fonlar hangileri?
- Fon portföy önerisinde ne kadar risk katkısı yaratıyor?
- Modelin geçmiş walk-forward doğrulaması ne söylüyor?
- Öneri hangi koşullarda zayıflar?

## Fazlar

### Faz 1 — Ürün hedefi ve yol haritası

- Bu dosya oluşturulur.
- Veri katmanı genişletmesinin kapsam dışında olduğu açıkça yazılır.
- Uygulama fazları ve kabul kriterleri netleştirilir.

Kabul kriteri:

- Plan dosyası repo kökünde bulunur.
- Plan, mevcut veri ve mevcut çıktı mimarisiyle uyumludur.

### Faz 2 — Tavsiye motoru semantiği

- Skorlama ile öneri katmanı birbirinden ayrılır.
- Uygunluk, profil sıralaması, izleme listesi ve portföy seçimi ayrı kararlar olarak modellenir.
- AUM getiri sinyali değil, likidite/uygunluk sinyali olarak ele alınır.
- Genç fonlar ana öneri yerine izleme listesine düşer.
- Risksiz faiz altında kalan düşük oynaklıklı fonlar açıkça “rf altı” bayrağı taşır.

Kabul kriteri:

- Profil bazlı öneriler deterministik üretilir.
- Uygun olmayan fon ana öneriye girmez.
- Genç fon ana öneri yerine izleme listesine ayrılır.
- rf altı fonlar doğru etiketlenir.

### Faz 3 — Model doğrulama

- Walk-forward backtest özeti ortak bir rapor/dashboard verisine dönüştürülür.
- 1A, 3A ve varsa 6A sonuçları aynı biçimde gösterilir.
- Backtest CSV yoksa sessiz geçilmez; kullanıcıya kontrollü uyarı üretilir.

Kabul kriteri:

- Geçerli CSV ile doğrulama özeti oluşur.
- Eksik CSV veya eksik kolon raporu kırmaz.
- PDF ve dashboard aynı özet fonksiyonunu kullanır.

### Faz 4 — PDF karar raporu

- PDF akışı karar odaklı hale getirilir.
- Karar özeti, önerilen portföy, uyarı bayrakları, model doğrulama, risk katkısı ve fon detayları daha belirgin hale getirilir.
- Risk katkısı ve korelasyon grafikleri daraltılmadan okunabilir boyutta gösterilir.

Kabul kriteri:

- PDF smoke test geçer.
- Eksik backtest/benchmark verisi PDF’i kırmaz.
- Risk katkısı grafiği okunabilir boyutta üretilir.

### Faz 5 — Dashboard karar akışı

- Mevcut dashboard korunur.
- Karar odaklı sayfalar veya bölümler eklenir:
  - Portföy Önerisi
  - Model Doğrulama
  - Risk Merkezi
- Dashboard sadece mevcut `Output/*.parquet` ve backtest CSV çıktılarını okur.
- Harici veri entegrasyonu yapılmaz.

Kabul kriteri:

- Dashboard veri hazırlama fonksiyonları test edilir.
- Output dosyaları yokken kontrollü mesaj üretilir.
- Backtest CSV yokken dashboard kırılmaz.

### Faz 6 — Model versiyonlama ve audit

- Skor ve öneri modeli ayarları tek yerde versiyonlanır.
- Rapor ve dashboard model versiyonunu gösterir.
- Backtest sonuçları model versiyonu ile ilişkilendirilir.

Kabul kriteri:

- Varsayılan model config yüklenir.
- Eksik config güvenli varsayılanla çalışır.
- Model versiyonu rapor/dashboard çıktısına yansır.

### Faz 7 — Stabilizasyon ve dokümantasyon

- README ve proje analizi güncellenir.
- Tüm testler çalıştırılır.
- Final pipeline ve report komutları doğrulanır.
- Geçici dosyalar repo’ya dahil edilmez.

Kabul kriteri:

- `python -m pytest -q` başarılıdır.
- `python -m tefas run --fund-type YAT --risk-free-rate 65 --config filter_config.txt` başarılıdır.
- `python -m tefas report --fund-type YAT --risk-free-rate 65` başarılıdır.


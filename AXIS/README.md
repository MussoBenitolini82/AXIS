# VECTOR Brain V2 — Canlı araştırma ve 3B bilgi grafiği

## Windows 11 kurulum

Python 3.10+ gerekir. Harici Python paketi gerektirmez.

```powershell
py server.py
```

Chrome/Edge ile `http://127.0.0.1:8765` açın. Arama kutusuna konu girip **Literatürü araştır ve beyne ekle** seçin. İnternet gerekir. OpenAlex'e erişim ağınıza ve API'nin kotalarına bağlıdır.

## Gerçekten çalışanlar
- OpenAlex akademik eser araması (başlık, DOI, yıl, varsa özet, kavram etiketleri)
- SQLite kalıcı bilgi grafiği ve kaynak bağlantıları
- Arka planda eşzamanlı araştırma işleri (en fazla üç çalışan iş)
- Döndürülebilen, yakınlaştırılabilen 3B izdüşümlü beyin grafiği (Canvas 2D üzerinde 3B koordinat dönüşümü)
- Makaleye tıklayınca kaynak ve özet gösterimi
- Arama başarısızlığı ve iş durumu gösterimi

## Henüz olmayanlar
- PDF tam metin indirme ve tarama, kaynaklar arası olgu doğrulama
- LLM ile sentez, yeni hipotez çıkarımı ve beceri orkestrasyonu
- Gerçek sinir ağının ağırlık/aktivasyon görselleştirmesi
- Otomatik uzman model eğitimi, güvenli kod üretimi ve bilgisayar işlemleri

Bu sürüm bilgi grafiğini gösterir; çizilen noktalar gerçek yapay nöronlar değildir. OpenAlex kavramları otomatik etiketlerdir; doğrulanmış bilimsel iddialar değildir.

## Gizlilik
Sunucu yalnızca `127.0.0.1:8765` adresinde dinler. Arama terimleri OpenAlex'e gönderilir. Yerel veriler `vector.db` dosyasında tutulur. Veritabanını silmek kayıtları kaldırır.
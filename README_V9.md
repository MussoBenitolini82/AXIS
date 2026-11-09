# VECTOR V9 — Ajan keşfi ve onaylı genişleme

Bu paket V8'i temel alır ve V9 ajan keşfi modülünü ekler. `KURULUM.bat` ve `BASLAT_VECTOR.bat` önceki gibi çalışır. V9 paneli sayfanın altındadır.

## Gerçek yetenekler
- Görev metnindeki ihtiyaçları yerel yetenek kataloğuna göre tarar.
- Mevcut uzman rollerini bulur; eksik görsel/ses/tarayıcı uzmanları için SQLite üzerinde **bekleyen rol önerisi** oluşturur.
- Kullanıcının açık onayı olmadan rolü etkinleştirmez.
- Onaylanan rol **yalnızca metadata/katalog kaydıdır**; model indirme, ajan kodu üretme veya araç bağlama değildir.
- Önceden var olan izinli salt-okunur hafıza araçlarını paralel çağırabilir.
- Ollama ve PyTorch için yerel sağlık kontrolü sağlar.

## Bilinçli sınırlar
Bu sürüm internette ajan keşfedip otomatik indirmez. Güvenilir bir ajan/model kataloğu, imza doğrulama, sürüm uyumluluk kontrolü, gerçek araç entegrasyonu ve insan onaylı kurulum için ayrıca geliştirme gerekir. Bu ayrım güvenlik açısından önemlidir.

## Kurulum
1. Windows 11: Python 3.11/3.12, Ollama, isteğe bağlı Docker Desktop.
2. `KURULUM.bat` çalıştır; `ollama pull qwen3:8b` komutuyla modeli indir.
3. `BASLAT_VECTOR.bat` çalıştır; `http://127.0.0.1:8765` adresini aç.
4. Alttaki VECTOR V9 panelinden görev taraması yap.
5. Test: `TEST_ET.bat` veya `VECTOR\.venv\Scripts\python.exe -m unittest discover -p "test*.py"`.

**Güvenlik notu:** Windows üzerinde Docker testleri izolasyon risklerini azaltır fakat mutlak güvenlik garantisi vermez. Kullanıcı onayı ve kod incelemesi gereklidir.
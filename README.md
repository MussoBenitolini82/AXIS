# AXIS — Yerel, çok ajanlı öğrenen masaüstü asistanı

AXIS V12 prototipinin kaynak kodları, Windows kurulum betikleri, testleri ve 3D beyin arayüzü için depo.

## Gereksinimler
- Windows 11, Python 3.11/3.12, Ollama
- Önerilen donanım: 32 GB RAM, NVIDIA RTX 4060 8 GB
- İsteğe bağlı Docker Desktop

## Başlangıç
1. `KUR_AXIS.bat` dosyasını çalıştırın.
2. `ollama pull qwen3:8b` ile modeli indirin.
3. `BASLAT_AXIS.bat` dosyasını çalıştırın.
4. `http://127.0.0.1:8765` adresini açın.

## Güvenlik ve durum
Bu bir geliştirme prototipidir. Yerel Ollama/Docker uçtan uca doğrulaması tamamlanmamıştır. API anahtarlarını, özel veritabanlarını veya yerel logları depoya eklemeyin.

**Aktarım durumu:** Kaynak kodların tamamı henüz depoya aktarılmamıştır.

# AXIS — Yerel, çok ajanlı öğrenen masaüstü asistanı

Bu depo AXIS V12 prototipinin kaynak kodlarını, Windows kurulum betiklerini, testlerini ve 3D beyin arayüzünü içerir. Önceki VECTOR adıyla yazılmış bazı modüller geriye dönük uyumluluk için korunmuştur.

## Gereksinimler
- Windows 11, Python 3.11/3.12, Ollama
- Önerilen donanım: 32 GB RAM, NVIDIA RTX 4060 8 GB
- İsteğe bağlı Docker Desktop (izole kod testi)

## Başlangıç
1. `KUR_AXIS.bat` dosyasını çalıştırın.
2. `ollama pull qwen3:8b` ile yerel modeli indirin.
3. `BASLAT_AXIS.bat` dosyasını çalıştırın.
4. Tarayıcıda `http://127.0.0.1:8765` adresini açın.

## Güvenlik ve durum
Bu bir geliştirme prototipidir. Yerel Ollama/Docker uçtan uca doğrulaması tamamlanmamıştır. Üretilen kodu onaylamadan önce gözden geçirin. Gerçek sandbox güvenliği yalnızca Docker kurulumuyla otomatik garanti edilmez. API anahtarlarını, özel veritabanlarını veya yerel logları depoya eklemeyin.

## Dizinler
- `AXIS/`: uygulama, ajanlar, merkezi hafıza, beceri yürütücüsü, testler
- `KUR_AXIS.bat`, `BASLAT_AXIS.bat`: Windows kurulumu ve başlatma
- `KURULUM_WINDOWS.ps1`: PowerShell kurulum yardımcısı

Önceki sürüm ZIP'leri ayrı arşivde tutulabilir; Git geçmişi yerine ZIP dosyalarını doğrudan commit etmek önerilmez.
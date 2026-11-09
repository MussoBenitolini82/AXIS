# VECTOR Brain V4 — Windows 11

## Kurulum

1. Python 3.11+ ve Ollama kur.
2. PowerShell'de: `ollama pull qwen3:8b`
3. Proje klasöründe: `py -m pip install -r requirements.txt`
4. `py server.py`
5. `http://127.0.0.1:8765` adresini aç.

Ollama servisinin çalışması gerekir. `VECTOR_MODEL` ortam değişkeniyle model değiştirilebilir.

## İşlevler

- OpenAlex üzerinden akademik **metadata/özet** taraması ve kaynaklı SQLite bilgi grafiği.
- Ollama ile *kayıtlı özetlere dayalı* Türkçe literatür sentezi. Tam metin okunduğu iddia edilmez.
- Yerel PDF yükleme ve PyMuPDF ile metin çıkarımı (en fazla 8 MB/100 sayfa). İlk 5500 karakter kaynak kaydına eklenir; PDF'nin tamamı hafızaya kaydedilmez.
- LLM ile yeni Python becerisi önerisi. AST kontrolü, diff, SHA-256, insan onayı, yedekleme. Kod **otomatik çalıştırılmaz**.
- Üç izinli salt-okunur aracın eşzamanlı çalışması. Genel bilgisayar kontrolü değildir.
- İnteraktif 3B bilgi grafiği. Gerçek model ağırlığı görselleştirmesi henüz yok.

## Güvenlik ve sınırlar

Bu uygulama yalnızca 127.0.0.1 üzerinde dinler; yine de yerel web sayfaları üzerinden erişime karşı üretim seviyesi kimlik doğrulama ve CSRF koruması yoktur. Güvenilmeyen kodu çalıştırma; AST filtresi sandbox değildir. Otomatik çekirdek güncelleme, Docker sandbox, gerçek ağırlık/aktivasyon görselleştirmesi ve kaynaklar arası semantik çelişki çözümü henüz uygulanmadı. Kod önerisini onaylamak sadece diske kaydeder, çalıştırmaz.
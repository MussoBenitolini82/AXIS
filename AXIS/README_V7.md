# VECTOR Brain V7 — Çok Ajanlı Kod Geliştirme

V6 üzerine eklenen **sıralı** üç LLM rolü: planlayıcı, kod yazarı, inceleyici. Roller tek bir Ollama modeline farklı istemlerle çağrı yapar; bağımsız uzman modeller oldukları iddia edilmez. İsteğin, planın, incelemenin, kod farkının ve onay durumunun kayıtları tutulur.

## Kurulum (Windows 11)

1. Python 3.11+, Ollama, isteğe bağlı PyTorch, Docker Desktop (Linux containers) kur.
2. `ollama pull qwen3:8b` ve `ollama serve` (Ollama zaten arka planda çalışıyorsa ikinci komuta gerek yok).
3. `py -m pip install -r requirements.txt` ve `py -m pip install torch`.
4. `docker pull python:3.12-slim`.
5. `py server.py`; `http://127.0.0.1:8765` aç.
6. V7 panelinden istek gönder. Kod incelemesi PASS olsa bile güncelleme uygulanmaz. V5 panelinde kod farkını incele, Docker testini çalıştır ve açık onay ver.

## Güvenlik ve sınırlamalar

- Ajanların kendi kodlarını doğrudan çalıştırma yetkisi yoktur. `server.py`, `vector_upgrade.py`, `vector_agents.py` ve onay kodu ajan güncellemesine kapalıdır.
- Docker testinde ağ kapalı, root olmayan kullanıcı, kaynak kısıtları, salt okunur bağlama ve statik AST sözleşme testi var. Bu test **işlevsel doğruluğu veya güvenliği kanıtlamaz**; Docker izolasyonu da mutlak güvenlik garantisi değildir.
- Onaydan sonra yalnızca `research_extensions.py` veya `skills_helpers.py` değişebilir. Yeni modül otomatik yüklenmez; uygulamayı yeniden başlatmak gerekebilir.
- Ajan kodu için işlevsel test üretme, proje çapında entegrasyon testi, bağımsız model bazlı ikinci inceleme ve Qwen3 iç aktivasyonlarının görselleştirilmesi henüz tamamlanmış değildir.
- İstekteki veya kod içindeki metinler güvenilmeyen girdidir. Yerel API yalnızca localhost'ta açılır; yerel makinedeki diğer süreçlere karşı kimlik doğrulaması sağlamaz.
- `GPT-6.1 Sol` burada çağrılabilir bir model değildir. Son kontrol yerine otomatik testler ve kullanıcı incelemesi vardır.

## Test
`py -m unittest discover -p "test_*.py" -v`
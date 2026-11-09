# VECTOR Brain V8 — Behavioral Test Agent

V7 üzerine yeni test tasarım rolü ekler. Ajanın ürettiği test vakaları JSON biçimindedir ve kaynak koddan ayrı tutulur. Kullanıcı `GET /api/behavior-cases?id=...` ile testleri inceleyebilir ve `POST /api/behavior-cases` ile düzenleyebilir. Örnek: `{"id":"...","cases":[{"function":"add","args":[2,3],"expected":5}]}`.

Docker doğrulaması varsa bu vakaları gerçek fonksiyonlara karşı çalıştırır; yoksa güvenli biçimde engeller. Testler sınırlı işlevsel doğrulama sağlar; kötü niyetli kodun güvenli olduğunu kanıtlamaz. Test ajanının vakaları model tarafından üretildiğinden bağımsız doğruluk kanıtı değildir. Değişiklik uygulamak için önceki açık insan onayı ve Docker doğrulaması hâlâ gerekir.

Bu sürümde Qwen3 transformer iç aktivasyonları veya GPT-6.1 Sol incelemesi bulunmaz. Docker / Ollama uçtan uca bu çalışma ortamında doğrulanmadı.

Kurulum: `py -m pip install -r requirements.txt`, `ollama pull qwen3:8b`, `docker pull python:3.12-slim`, `py server.py`. Test: `py -m unittest discover -p "test_*.py" -v`.
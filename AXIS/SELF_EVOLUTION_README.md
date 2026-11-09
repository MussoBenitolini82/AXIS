# VECTOR Brain V3 — Onaylı öz-değişim prototipi

`py server.py` ile başlatıp http://127.0.0.1:8765 açın. Sayfanın altındaki Self-Evolution bölümünde bir Python becerisi önerin. Örnek kod:

```python
def run(data):
    return {'result': str(data).upper()}
```

Önce farkı (diff) ve sözdizimi kontrolünü görün. Onayladığınızda yalnızca `skills/<beceri>.py` yazılır. Eski sürüm `backups/` altına kopyalanır. Kod otomatik çalıştırılmaz. Bu sistemde LLM henüz kod yazmaz ve önerilen kod için gerçek izolasyon/sandbox uygulanmaz; AST kuralları güvenlik garantisi değildir. Bu nedenle beceri dosyalarını çalıştırmadan önce ayrıca inceleyin. Core dosyaları otomatik düzenlenmez. Yerel API, yalnızca 127.0.0.1 üzerinde dinler; localhost üzerindeki diğer programlara karşı kimlik doğrulama sağlamaz. Gerçek üretim sürümü için yetkilendirme, CSRF koruması, Windows Sandbox/VM ve test süreci gereklidir.
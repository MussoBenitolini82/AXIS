# Çoklu yapay zekâ denetimi

Standart Python kütüphanesiyle çalışır; yeni paket gerekmez. Önceki Windows kaynak görüntüsü ve SQLite düzeltmeleri AXIS/ içinde korunmuştur. Bu dal uzak Git geçmişiyle eşitlenmiş değildir; push öncesinde kimlik doğrulanmış checkout üzerinde kaynak tabanı ile uzlaştırılmalıdır.

## Kullanım

Python 3.12 ortamınızla, depo kökünden:

    python AXIS/multi_ai_review.py axis_sqlite.py multi_ai_review.py

Bu komut model atamaz; bağlantı durumunu ve beş rolün çalıştırılmama nedenlerini raporlar. Kurulu, yerel bir model açıkça seçildiğinde:

    python AXIS/multi_ai_review.py axis_sqlite.py --model MODEL_ADI

Programatik `run(paths, assignments)` çağrısı her role farklı model atayabilir. Rol anahtarları: Developer, Reviewer, Security Auditor, Test Engineer. Coordinator model kullanmadan özet çıkarır. Aynı modelde farklı rol istemleri bağımsız sağlayıcı incelemesi sayılmaz.

Her çalışma reports/ altında benzersiz bir klasör, beş görev/rol raporu ve summary.json oluşturur. Durumlar COMPLETED, FAILED veya NOT_RUN'dır. Kaynak hash'i, zaman, görev, sağlayıcı/model, bulgular ve eksik bağlantılar saklanır. Başarılı görünen model yanıtı otomatik onay değildir.

## Sağlayıcı araştırması

- Ollama: yerel model listesi ve sohbet API'si desteklenir; model seçimi kurulu listeye bağlıdır. Şu an liste boş. https://docs.ollama.com/api
- Claude: bağımsız Anthropic sağlayıcısı; resmi model listesi ve Messages API üzerinden kullanılabilir. Bu ortamda yetkili bağlantı yok, adaptör etkin değil. https://platform.claude.com/docs/en/models/overview
- Gemini: bağımsız Google sağlayıcısı; güncel kullanılabilirlik resmi model listesinden doğrulanmalıdır. Bu ortamda yetkili bağlantı yok, adaptör etkin değil. https://ai.google.dev/gemini-api/docs/models

Bulut API anahtarı bulunması ücretli kullanıma izin sayılmaz. Bu uygulama buluta kaynak göndermez. Paket/model kurulumu, ücretli API ve main birleştirmesi öncesi kullanıcı onayı gerekir. Hassas kaynakları denetime vermeyin; temel maskeleme tüm sırları yakalama garantisi sağlamaz.

Test: `cd AXIS` ardından `python -m unittest discover -p 'test*.py' -v`.

# Çoklu yapay zekâ denetimi

Standart Python kütüphanesiyle çalışır; yeni paket gerekmez. Önceki Windows kaynak görüntüsü ve SQLite düzeltmeleri AXIS/ içinde korunmuştur. Bu dal uzak Git geçmişiyle eşitlenmiş değildir; push öncesinde kimlik doğrulanmış checkout üzerinde kaynak tabanı ile uzlaştırılmalıdır.

## Kullanım

Python 3.12 ortamınızla, depo kökünden:

    python AXIS/multi_ai_review.py axis_sqlite.py multi_ai_review.py

Bu komut model atamaz; bağlantı durumunu ve beş rolün çalıştırılmama nedenlerini raporlar. Kurulu, yerel bir model açıkça seçildiğinde:

    python AXIS/multi_ai_review.py axis_sqlite.py --model MODEL_ADI --timeout 600

Bağlam penceresi: Ollama, `num_ctx` değerinden uzun bir istemin başını sessizce atar. Bu yüzden araç `num_ctx` değerini paket boyutundan, karakter başına 2,5 token varsayımıyla ve çıktı payını ekleyerek hesaplar. Paket modelin bağlam sınırını aşıyorsa model çağrılmaz. Model bağlam sınırını bildirmiyorsa ya da istem pencereyi doldurmuşsa (`prompt_eval_count` ≥ `num_ctx` − çıktı payı) rol `FAILED: ContextTruncated` olur. Raporda `num_ctx` ve `prompt_eval_count` saklanır.

Çıktı: istekte `think: false` gönderilir (qwen3 düşünme çıktısı JSON'u bozmasın). Çıktı payı 4096 token'dır; `done_reason == 'length'` ya da `eval_count` ≥ payı ise yanıt eksiktir ve rol `FAILED: OutputTruncated` olur. Raporda `done_reason` ve `eval_count` saklanır; sağlayıcı değerleri güvenilmez sayılır: sayaçlar yalnızca int ise, `done_reason` yalnızca str ise (maskelenip en çok 40 karakter) yazılır, aksi halde `null`. `findings` listesi yoksa ya da 100'den fazlaysa neden `ValueError: Invalid finding schema: findings` olur; `/api/tags` geçersiz model adı döndürürse bağlantı `UNAVAILABLE:ValueError` sayılır. Yanıt alındıktan sonra JSON/şema hatası olursa ham yanıtın temizlenmiş (`scrub`) ilk 4000 karakteri `raw_response_excerpt` alanına yazılır.

Fail-closed doğrulama: `/api/chat` yanıtında `prompt_eval_count` (bool olmayan int, > 0), `eval_count` (bool olmayan int, >= 0) ve `done_reason == 'stop'` yoksa ya da geçersizse rol `FAILED: ResponseUnverifiable` olur; `OutputTruncated` ve `ContextTruncated` korunur.

Bulgu şeması: bulgular serileştirilmiş JSON üzerinde `scrub` ile değil, doğrulanmış alanlardan yeni sözlükler kurularak temizlenir. Yalnızca severity (critical/high/medium/low/info; küçük harfe çevrilir), file (str, en çok 300), line (int ya da None), confidence (str, en çok 50), explanation (str, en çok 4000) ve isteğe bağlı suggested_fix (str, en çok 4000) saklanır; fazla anahtarlar atılır ve sayısı `dropped_finding_keys` alanına yazılır. Geçersiz alan rolü `FAILED` yapar, neden `ValueError: Invalid finding schema: <alan>` olur (ham model içeriği nedene yazılmaz).

Maskeleme (`scrub`): password/passwd/secret/secret_key/private_key/token/api_key/access_key/client_secret anahtar-değer çiftleri (tırnaklı JSON/Python biçimleri dahil; değer tırnaklarıyla birlikte), Bearer belirteçleri, AKIA, github_pat_, gh*_, xox*-, sk-, AIza anahtarları, `şema://kullanıcı:parola@sunucu` kimlik bilgileri ve çok satırlı PEM PRIVATE KEY blokları.

Programatik `run(paths, assignments)` çağrısı her role farklı model atayabilir. Rol anahtarları: Developer, Reviewer, Security Auditor, Test Engineer. Coordinator model kullanmadan özet çıkarır. Aynı modelde farklı rol istemleri bağımsız sağlayıcı incelemesi sayılmaz.

Her çalışma reports/ altında benzersiz bir klasör, beş görev/rol raporu ve summary.json oluşturur. Durumlar COMPLETED, FAILED veya NOT_RUN'dır. Kaynak hash'i, zaman, görev, sağlayıcı/model, bulgular ve eksik bağlantılar saklanır. Başarılı görünen model yanıtı otomatik onay değildir.

## Sağlayıcı araştırması

- Ollama: yerel model listesi ve sohbet API'si desteklenir; model seçimi kurulu listeye bağlıdır. Şu an liste boş. https://docs.ollama.com/api
- Claude: bağımsız Anthropic sağlayıcısı; resmi model listesi ve Messages API üzerinden kullanılabilir. Bu ortamda yetkili bağlantı yok, adaptör etkin değil. https://platform.claude.com/docs/en/models/overview
- Gemini: bağımsız Google sağlayıcısı; güncel kullanılabilirlik resmi model listesinden doğrulanmalıdır. Bu ortamda yetkili bağlantı yok, adaptör etkin değil. https://ai.google.dev/gemini-api/docs/models

Bulut API anahtarı bulunması ücretli kullanıma izin sayılmaz. Bu uygulama buluta kaynak göndermez. Paket/model kurulumu, ücretli API ve main birleştirmesi öncesi kullanıcı onayı gerekir. Hassas kaynakları denetime vermeyin; temel maskeleme tüm sırları yakalama garantisi sağlamaz.

Test: `cd AXIS` ardından `python -m unittest discover -p 'test*.py' -v`.

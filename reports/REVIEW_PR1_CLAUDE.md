# PR #1 inceleme raporu — Claude

| Alan | Değer |
|---|---|
| İnceleyen / sağlayıcı / model | Claude Code / Anthropic / claude-opus-5-5 |
| Zaman (UTC) | 2026-11-09T21:06:41Z |
| PR | https://github.com/MussoBenitolini82/AXIS/pull/1 |
| İncelenen commit | 2c3f099a175cf3d66882d2bab88a3dc06751019d (taban cb46e24) |
| Diff SHA-256 | `git diff cb46e24 2c3f099` → ef59ee197bc2ab0638f6dc95f84301a28a1b1551b2bde07156d6e2603b778cca |
| Kapsam | 18 dosyanın tamamı: kod, testler, .gitignore, belgeler |

## Bağımsızlık beyanı
- **Bağımsız inceledim:** `axis_sqlite.py`, SQLite bağlantı değişiklikleri, `multi_ai_review.py` ve testleri. Bunlar Codex çalışmasıdır.
- **Bağımsız sayılmaz:** `--memory-swap` eklemesi, import'ların docstring altına taşınması, `.gitignore`'a `!.env.example` eklenmesi, `reports/ENVIRONMENT_VERIFICATION_20261109.md` ve plan dosyasındaki yol temizliği. Bunları bu oturumda Claude yazdı.
- **Codex:** AGENTS.md'ye göre Codex birincil kodlama ajanıdır. Codex'in onayı yazar onayıdır; iki bağımsız sağlayıcıdan biri yerine geçmez.

## Doğrulama yöntemi
Kod okuma, Python 3.12.10 ile birim testleri (54 çalıştı: 50 geçti, 4 atlandı, torch yok), GitHub Actions `unittest` (başarılı), Docker cgroup ölçümü ve yerel Ollama (qwen3:8b) üzerinde ölçüm. Bulgular test veya ölçümle desteklenmiştir; model görüşü tek başına kanıt sayılmamıştır.

## Bulgular

| # | Önem | Dosya:satır | Güven | Bulgu |
|---|---|---|---|---|
| 1 | **Yüksek** | AXIS/multi_ai_review.py:87 | Yüksek (ölçüldü) | Sohbet çağrısı `num_ctx` vermiyor, Ollama varsayılan ~2048 token bağlamı kullanıyor. Ölçüm: `server.py + vector_upgrade.py + multi_ai_review.py` paketi 33.656 karakter, modele ulaşan `prompt_eval_count` = 2050. Kaynağın büyük kısmı sessizce kesiliyor ama rapor `COMPLETED` yazıyor. Model kodun tamamını görmeden "bulgu yok" diyebilir. **Öneri:** `num_ctx`'i paket boyutuna göre ayarlamak (model sınırı 40960); yanıttaki `prompt_eval_count` beklenen token sayısının altındaysa durumu `FAILED: truncated` yapmak. |
| 2 | Orta | AXIS/test_multi_ai_review.py | Yüksek | 1. bulguyu yakalayacak test yok. Sahte API, `prompt_eval_count` döndürmüyor ve gönderilen `options` doğrulanmıyor. Ayrıca `vector_upgrade` Docker komutundaki güvenlik bayraklarını (`--network none`, `--read-only`, `--memory-swap` vb.) doğrulayan birim testi yok; bir bayrağın kaldırılması testleri kırmaz. |
| 3 | Düşük | AXIS/multi_ai_review.py:49 | Orta | 180 sn sohbet zaman aşımı bu makinede (yalnızca CPU, ilk yükleme 44 sn, kısa yanıt toplam 79 sn) bağlam büyütülünce yetmeyebilir. Hata güvenli tarafta kalıyor (`FAILED`), ama tam paket incelemeleri pratikte hep başarısız olabilir. Zaman aşımı yapılandırılabilir olmalı. |
| 4 | Düşük | AXIS/multi_ai_review.py:62 | Yüksek | Varsayılan çıktı deponun `reports/` klasörü. `.gitignore` yalnızca `reports/**/raw*` desenini dışlıyor, dolayısıyla her çalıştırma izlenmeyen `summary.json` ve rol dosyaları bırakıyor; bunlar yanlışlıkla commit edilebilir. `reports/2*/` dışlanmalı ya da çıktı `AXIS/data/` altına alınmalı. |
| 5 | Bilgi | .gitignore | Yüksek | `*.py[cod]` yerine `*.pyc` gelmiş; `.pyo`/`.pyd` artık dışlanmıyor. Pratik etkisi düşük. |
| 6 | Bilgi | AXIS/multi_ai_review.py:79 | Yüksek | `'/' in model` koşulu ad alanlı yerel modelleri (ör. `kullanici/model`) de reddediyor. Güvenli tarafta; belgelenmeli. |

## Sorun bulunmayan alanlar
- **ClosingConnection:** `__exit__`, commit/rollback sonrasında `close()` çağırıyor ve istisnaları yutmuyor. Değiştirilen 8 modüldeki tüm bağlantı fabrikası çağrıları `with … as` ile kullanılıyor. Kapanıştan sonra kullanılan imleç döndüren kod ve fabrikasız `sqlite3.connect` kalmamış. İki regresyon testi commit ve rollback yollarını kapsıyor.
- **Docker sandbox:** `--memory-swap 512m` ile `memory.swap.max = 0` oluyor; 600 MB ayırma OOM ile sonlanıyor (rc 137). 11/11 izolasyon kontrolü geçti. Docker yoksa `verify()` BLOCKED döndürüyor, host'ta çalıştırma yok. *(Bu kısım bağımsız değildir.)*
- **multi_ai_review güvenlik sınırları:** Yalnızca loopback adresi, proxy kapalı, yönlendirme yasak. 1 MB yanıt sınırı, üst düzey `.py` dosyası dışında kaynak reddi, sır maskeleme, bulut modeli reddi ve bulgu şeması doğrulaması var. Bağımsız sağlayıcı incelemesi kodda sabit olarak `NOT_RUN` yazılıyor, rol çeşitliliği bağımsızlık olarak sayılmıyor.
- **Sırlar:** Diff'te gerçek sır yok; tek eşleşme testteki sahte değer.

## Düzeltme takibi
- **1 — DÜZELTİLDİ (Claude yazdı, bağımsız değil).** `num_ctx`, bağlam sınırı ve kesilme tespiti eklendi; ayrıntılar MULTI_AI_REVIEW.md'de.
- **2 — DÜZELTİLDİ.** Kesilme için 4 test eklendi; bu testler eski kodda başarısız oluyor (5 FAIL, 1 ERROR). `test_vector_upgrade_sandbox.py` Docker güvenlik bayraklarını ve Docker yokken BLOCKED davranışını doğruluyor; `--memory-swap` kaldırılınca test başarısız oluyor.
- **3 — DÜZELTİLDİ.** Zaman aşımı varsayılanı 600 sn yapıldı ve `--timeout` ile ayarlanabiliyor.
- **4 — DÜZELTİLDİ.** `.gitignore` artık `reports/[0-9]*T[0-9]*-*/` desenini içeriyor.
- **Ek (qwen3 gerçek çalıştırma FAILED/JSONDecodeError):** İstek artık `think: false` gönderiyor ve çıktı payı 4096 token. `OutputTruncated` tespiti eklendi; hata olursa temizlenmiş ham yanıt `raw_response_excerpt` alanına yazılıyor. Bunun için 4 test var. Gerçek model üzerinde yeniden çalıştırılmadı.
- **5, 6 — AÇIK** (bilgi düzeyi).
- Tam takım: 64 test, 60 geçti, 4 atlandı (torch yok).

## Karar
**Koşullu onay.**
- SQLite düzeltmesi, Docker sertleştirmesi ve `.gitignore` birleştirilebilir durumda.
- `multi_ai_review.py` çalışma zamanını etkilemiyor, yalnızca danışman niteliğinde. Ancak 1. bulgu düzeltilmeden bu aracın çıktısı **inceleme kapısı olarak kullanılmamalı**, çünkü kesilmiş bir incelemeyi tamamlanmış gösteriyor.
- Bu raporla gereken iki bağımsız sağlayıcıdan biri tamamlandı. Gemini incelemesi alınana kadar AGENTS.md'ye göre birleştirme koşulu karşılanmış değil.

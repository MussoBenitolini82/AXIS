# qwen3:8b bulgularının doğrulanması

- Model: qwen3:8b (yerel, tek model; bağımsız bir sağlayıcı DEĞİLDİR)
- Kaynak rapor: reports/REAL_RUN_QWEN3_PR1.md, anlık görüntü commit 26f5cca
- Doğrulanan kod: HEAD 8828dac (f71f578 ve b91abc3 sonrası)
- Yöntem: kod okuma + kopya üzerinde `py -3.12 -I` ile yeniden üretim (scratchpad\validateQ). Hiçbir kod değiştirilmedi, commit yapılmadı, dış model çağrılmadı.
- Not: Modelin satır numaraları büyük oranda uydurmadır (axis_sqlite.py 9, vector_upgrade.py 198, multi_ai_review.py 253 satır; model 284'e kadar satır vermiş). Tabloda HEAD'deki gerçek satırlar verilmiştir.

## Bulgu tablosu

| id | Orijinal önem | HEAD'de dosya:satır | Özet | Durum | Kanıt |
|---|---|---|---|---|---|
| Q1 | medium | axis_sqlite.py:5-9 | `__exit__` super'i çağırmıyor | YANLIŞ POZİTİF | Satır 7 `super().__exit__` çağırıyor, `finally` ile kapatıyor |
| Q2 | low | vector_upgrade.py:7 | `mkdir(exist_ok=True)` parents yok | YANLIŞ POZİTİF | DATA'nın üst dizini (ROOT) zaten var; parents gereksiz |
| Q3 | medium | vector_upgrade.py:12-14 | `connection()` hata durumunda kapatmıyor | CONFIRMED (düşük) | `with connection()` ClosingConnection ile kapanır; yalnızca satır 14'te `CREATE TABLE`/`commit` hata verirse `c` sızar (kod okumasıyla, çalıştırılmadı) |
| Q4 | medium | vector_upgrade.py:16 | 'çekirdek' hata mesajı güvenlik riski | YANLIŞ POZİTİF | Sabit, zararsız mesaj; gizli veri içermiyor |
| Q5 | medium | vector_upgrade.py:18-21 | `ast.parse` hataları yakalanmıyor | CONFIRMED | Yeniden üretildi: `propose('research_extensions.py','def f(:')` SyntaxError fırlatıyor (ValueError/TypeError değil); server.py bu istisnayı 400 kapsamında yakalamıyor, 503 döner. (`ast.ParseError` diye bir sınıf yok, model adı yanlış) |
| Q6 | medium | vector_upgrade.py:22-37 | CONTRACT_TEST çok satırlı betik riski | YANLIŞ POZİTİF | Sabit metin; yalnızca Docker içinde (ağ yok, read-only) çalışır |
| Q7 | medium | vector_upgrade.py:59-66 | `attach_behavior_cases` doğrulamadan yazıyor | YANLIŞ POZİTİF | Satır 64 `validate_behavior_cases` çağırıyor (sınırlı JSON literal) |
| Q8 | medium | vector_upgrade.py:68-76 | `behavior_cases` JSON'u doğrulamadan okuyor | NOT REPRODUCED | Dosyayı yalnızca doğrulanmış yazım yolu üretir, digest karşılaştırılıyor; yerel güvenilir dizin |
| Q9 | medium | vector_upgrade.py:78-92 | BEHAVIOR_RUNNER betik riski | YANLIŞ POZİTİF | Q6 ile aynı gerekçe: sabit metin, yalnızca konteyner içinde çalışır |
| Q10 | medium | vector_upgrade.py:94-98 | `docker_available` istisna yakalamıyor | YANLIŞ POZİTİF | Satır 98 `OSError`, `TimeoutExpired` yakalıyor |
| Q11 | medium | vector_upgrade.py:99-105 | `propose` doğrulamadan yazıyor | YANLIŞ POZİTİF | Satır 100 `safe_target` + `validate` yazmadan önce çağrılıyor |
| Q12 | medium | vector_upgrade.py:106-114 | `detail` dosyayı doğrulamadan okuyor | YANLIŞ POZİTİF | Kendi yazdığımız dosya, hedef `safe_target` ile kısıtlı; yalnızca diff için okuma |
| Q13 | medium | vector_upgrade.py:115-116 | `listing` istisna işlemiyor | NOT REPRODUCED | Bağlantı `with` ile kapanır; hata yayılması bilinçli davranış, kaynak sızıntısı yok |
| Q14 | medium | vector_upgrade.py:147-160 | `verify` içinde `subprocess.run` istisnaları yakalanmıyor | FIXED SINCE (b91abc3) | 26f5cca'da `OSError` (docker kaybolması) yakalanmıyordu; HEAD satır 160 ekledi; `TimeoutExpired` zaten vardı |
| Q15 | medium | vector_upgrade.py:183-185 | `decide` dosya işlemleri hata yönetimi | CONFIRMED (düşük-orta; model gerekçesi farklı) | Yeniden üretildi: `os.replace` sonrası DB `UPDATE` hata verirse (database is locked) hedef dosya değişmiş, durum 'pending' kalıyor, yedek kaydı yok. Dosya hataları ise temiz yayılıyor (temp `finally` ile siliniyor) |
| Q16 | medium | vector_upgrade.py:195-197 | `rollback` dosya işlemleri hata yönetimi | NEEDS DECISION | Q15'teki DB-sonrası tutarsızlık burada da geçerli; ayrıca `shutil.copy2(backup,dest)` atomik değil (`os.replace` yok), yazma ortasında kesilirse dest bozulur. Öncelik kararı gerekli |
| Q17 | medium | multi_ai_review.py:15 | 'Security Auditor' rolü denetim zorlamıyor | YANLIŞ POZİTİF | ROLES yalnızca model istem metnidir; zorlama amacı yok |
| Q18 | medium | multi_ai_review.py:19 | `_KEYS` SECRET_PATTERNS'ta kullanılmıyor | YANLIŞ POZİTİF | Satır 31'de kullanılıyor (f71f578 ile `secret_key`, `private_key` eklendi) |
| Q19 | medium | multi_ai_review.py:21-94 | SECRET_PATTERNS `scrub()` içinde kullanılmıyor | YANLIŞ POZİTİF | Satır 92-93 döngüyle hepsini uyguluyor |
| Q20 | medium | multi_ai_review.py:62-68 | `plan_context` limit 0/yok durumunu işlemiyor | YANLIŞ POZİTİF | `context_limit` (55-60) limit yoksa/≤0 ise `ContextTruncated` fırlatıyor; `num_ctx > limit` de kontrol ediliyor |
| Q21 | medium | multi_ai_review.py:73-89 | `check_response` tüm hataları işlemiyor | NOT REPRODUCED | Belirsiz iddia; fonksiyon fail-closed (eksik/geçersiz sayaç, length, done!=stop hepsi hata) |
| Q22 | medium | multi_ai_review.py:91-94 | `scrub` tüm durumları işlemiyor | NEEDS DECISION | İddia genel, ama gerçek boşluklar var (aşağıda). Sezgisel temizleyici doğası gereği eksiktir; kabul/genişletme kararı gerekli |
| Q23 | medium | multi_ai_review.py:96-99 | `_text` tüm durumları işlemiyor | NOT REPRODUCED | Tür ve uzunluk kontrolü yapıp hata fırlatıyor, ardından scrub |
| Q24 | medium | multi_ai_review.py:101-123 | `sanitize_findings` tüm durumları işlemiyor | NOT REPRODUCED | Belirsiz iddia; şema, önem, satır (bool dahil) doğrulanıyor, taze dict üretiliyor |
| Q25 | medium | multi_ai_review.py:125-146 | `bundle` tüm durumları işlemiyor | NOT REPRODUCED | Belirsiz iddia (bilgi: boş liste, yinelenen dosya, düzenli olmayan dosya kontrolleri f71f578 ile eklendi) |
| Q26 | medium | multi_ai_review.py:152-162 | `local_api` tüm durumları işlemiyor | NOT REPRODUCED | Belirsiz iddia (bilgi: 26f5cca'da `show` çağrısı da 600 sn zaman aşımı kullanıyordu; f71f578 META_TIMEOUT ile düzeltti) |
| Q27 | medium | multi_ai_review.py:164-242 | `run` tüm durumları işlemiyor | NOT REPRODUCED | Belirsiz iddia; model çağrıları tek `try/except Exception` içinde, FAILED olarak kaydediliyor |

## Özet (duruma göre)

| Durum | Adet | Bulgular |
|---|---|---|
| CONFIRMED | 3 | Q3, Q5, Q15 |
| FIXED SINCE | 1 | Q14 (b91abc3) |
| NEEDS DECISION | 2 | Q16, Q22 |
| YANLIŞ POZİTİF | 13 | Q1, Q2, Q4, Q6, Q7, Q9, Q10, Q11, Q12, Q17, Q18, Q19, Q20 |
| NOT REPRODUCED | 8 | Q8, Q13, Q21, Q23, Q24, Q25, Q26, Q27 |
| DUPLICATE | 0 | - |
| Toplam | 27 | |

Modelin bulgularının büyük çoğunluğu (21/27) yanlış ya da belirsiz. Doğrulananların hiçbiri yüksek önemli değil.

## Gerçek açık bulgular

1. **Q5 (düşük-orta)**: `validate()` geçersiz Python'da `SyntaxError` yayıyor; server.py bunu 503 yapıyor, istemci hatası olarak 400 dönmeli.
   Öneri: `try: ast.parse(code)` bloğunu `except (SyntaxError, ValueError, RecursionError, MemoryError) as e: raise ValueError('Geçersiz kod') from e` ile sar.
2. **Q15 (düşük-orta)**: `decide()` dosyayı `os.replace` ile değiştirdikten sonra DB güncellemesi başarısız olursa dosya uygulanmış, durum 'pending'.
   Öneri: DB güncellemesini `try/except` ile sar; hata halinde yedekten geri yükle (`os.replace(backup, dest)`, yedek yoksa `dest.unlink`). Alternatif: önce durumu 'applying' yaz, sonra 'applied' yap ve açılışta 'applying' kayıtlarını uzlaştır.
3. **Q3 (düşük)**: `connection()` içinde `CREATE TABLE`/`commit` hatasında bağlantı kapanmıyor.
   Öneri: `try: ... except BaseException: c.close(); raise`.
4. **Q16 (düşük, karar)**: `rollback()` `shutil.copy2(backup,dest)` ile yerinde yazıyor, atomik değil; DB güncelleme hatası Q15'teki gibi tutarsızlık yaratır.
   Öneri: `decide()`'daki temp dosya + `os.replace` kalıbı ve Q15'teki hata yönetimi.
5. **Q22 (düşük, karar)**: `scrub` şu biçimleri temizlemiyor (yeniden üretildi): `os.environ["TOKEN"] = "..."` (anahtar ile `=` arasında `]`), `Authorization: Basic <b64>`, `Cookie: session=...`, `pwd=...`.
   Öneri: kalıbı `["\']?\]?` ile abonelik biçimine genişlet, `Basic\s+...` ve `pwd|cookie|session` anahtarlarını ekle; ya da sınırı belgele.

## Ek bulgu (modelden bağımsız, doğrulama sırasında bulundu)

- **Windows'ta CRLF digest uyuşmazlığı (orta)**: `propose()` kodu `write_text` ile yazıyor (Windows'ta `\n` -> `\r\n`), digest ise `code.encode()` üzerinden hesaplanıyor. `decide()` satır 176'da `src.read_bytes()` digest'ini karşılaştırıyor; çok satırlı kodda her zaman "Kod değişmiş" hatası veriyor (yeniden üretildi: staged baytlarda CRLF var, digest eşleşmiyor). `verify()` `read_text` kullandığı için eşleşiyor. Öneri: `write_bytes(code.encode('utf-8'))` ile yaz, ya da `write_text(..., newline='')`.

## Yeniden üretim dosyaları

C:\Users\ilkeb\AppData\Local\Temp\claude\0846e75a7d16bbd7\5bbf40f4-2b90-4eff-8fd4-914e43cc6b59\scratchpad\validateQ\repro.py, repro2.py, repro3.py (kopya dizin; depoda değil).

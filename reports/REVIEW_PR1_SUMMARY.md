# PR #1 inceleme özeti ve bulgu doğrulaması

- Commit: 5ee362b (taban cb46e24; çalışma ağacı HEAD 3011867, sonrasında yalnızca belge/diff eklendi)
- İnceleyenler: Claude (yalnızca Codex'in yazdığı kısımlar için bağımsız; Claude'un önceki raporu 2c3f099 üzerindeydi), Gemini (bağımsız, parçalı/satır içi diff, 5 çağrı), Codex (yazar görüşü, bağımsız değil)
- qwen3 yerel model: NOT RUN
- Doğrulama: bu belgeyi yazan doğrulayıcı; Gemini ve Codex bulguları kod okuma ve scratch kopyada çalıştırılan betiklerle sınandı. Kod düzeltilmedi, commit yapılmadı.
- Scratch: `...\scratchpad\validate` (`repro.py`, `repro2.py`, `repro_docker.py`; `py -3.12 -I`). Scratch kopyada mevcut 14+2+2 test (multi_ai_review, vector_upgrade_sandbox, axis_sqlite) geçti.
- Gemini satır numaraları parçaya göredir; tabloda gerçek dosya satırı verilmiştir (G7-G15 için Gemini'nin numaraları gerçek satırlarla zaten örtüşüyor, G10 için 122 yerine gerçek satır 124/126).

## Sayılar

36 Gemini + 2 Codex = 38 bulgu.
- CONFIRMED: 26 (Gemini)
- NOT REPRODUCED: 7 (Gemini)
- NEEDS DECISION: 3 (Gemini)
- DUPLICATE: 2 (Codex C1, C2; her ikisi de Gemini'de onaylanan bulgunun aynısı)

## Fidelity (elle yeniden yazılmış diff)

- Gemini'ye gönderilen yeniden yazılmış parça metinleri `REVIEW_PR1_GEMINI.md` içinde KAYITLI DEĞİL; yalnızca yanıtlar ve kurye sapma notu var. Bu yüzden parça-parça satır karşılaştırması yapılamadı.
- Dolaylı kanıtlar: (1) `reports/PR1_5ee362b.diff` SHA-256 = 4f7504b1... ve bu, `git diff cb46e24 5ee362b` çıktısından `reports/REVIEW_PR1_CLAUDE.md` hariç tutulunca birebir aynı (50849 bayt; 19 dosya; REVIEW_PR1_CLAUDE.md eklenen ek dosya, Gemini'ye kapsam dışı). Yani chunk'lamadan önceki diff doğru; elle yeniden yazım sonraki adım. (2) Gemini'nin alıntıladığı kod parçaları gerçek koda birebir uyuyor: SECRET regex'i, `json.loads(scrub(json.dumps(findings)))`, `timeout=CHAT_TIMEOUT if payload else 5`, docker `--mount`/`--tmpfs` dizgisi, `script` içindeki `/work/'+r['target']+'`. Parça 2'deki satır numaraları (18, 33, 48, 64, 83, 142, 148, 177) gerçek dosya satırlarıyla aynı; sadece 122 gerçekte 124.
- Sonuç: CODE satırı farkı tespit edilmedi (kanıt dolaylı; tam doğrulama mümkün değil). Kurye notundaki belge farkı: `IMPLEMENTATION_REVIEW.md` "Security controls" satırında gerçek metin "auto-apply or merge" (Gemini'ye "auto-apply or manual merge" gitmiş) ve `index ...` başlık satırları; ikisi de belge/üstbilgi, bulguları etkilemiyor.

## Bulgu tablosu

Önem sütunu kaynağın bildirdiği değerdir; değerlendirme farklıysa kanıt sütununda belirtilmiştir.

| Id | Kaynak | Önem | Dosya:satır | Özet | Durum | Kanıt | Örtüşme |
|---|---|---|---|---|---|---|---|
| G1 | Gemini | medium | AXIS/vector_upgrade.py:12-15 (ve 7 benzeri fabrika) | `connect()` sonrası PRAGMA/CREATE hata verirse bağlantı `with`'e girmediği için kapanmıyor | CONFIRMED (gerçek etki düşük) | `repro2.py`: bozuk DB ile `connection()` DatabaseError verdi; hemen `os.unlink` WinError 32, `gc.collect()` sonrası silindi. Regresyon değil, değişiklikten önce de aynıydı. Değerlendirme: low | - |
| G2 | Gemini | medium | AXIS/axis_sqlite.py:4-9 | `__exit__` içinde close(); with dışı/yeniden kullanım kırılır | NOT REPRODUCED | 8 modülde tüm fabrika çağrıları `with ... as` içinde (grep); `with` sonrası imleç/bağlantı kullanımı yok; `sqlite3.connect` fabrikasız kalmadı | Claude "Sorun bulunmayan alanlar" ile aynı sonuç |
| G3 | Gemini | low | AXIS/test_axis_sqlite.py | Yalnızca `ClosingConnection` yalıtık test ediliyor, 8 modülün fabrikası ve iş akışı yok | CONFIRMED | Kod okuma (31 satır, 2 test: commit/rollback) | - |
| G4 | Gemini | low | .gitignore:3-8 | `*.db*`/`*.sqlite*`/`.env*` fazla geniş; `*.py[cod]` yerine `*.pyc` (.pyo/.pyd artık yok sayılmıyor) | CONFIRMED | `git check-ignore -v`: `docs.db_notes.md` ve `test_db.sqlite_helper.py` yok sayılıyor, `x.pyo` yok sayılmıyor | Claude #5 (pyc kısmı) |
| G5 | Gemini | low | .gitignore:9 | `AXIS/skills/` takip edilen dosyaları gizleyebilir | NOT REPRODUCED | `git ls-files AXIS/skills` boş | - |
| G6 | Gemini | info | AXIS/*.py (axis_sqlite importu) | Düz `from axis_sqlite import` AXIS/ dizinini gerektirir | NOT REPRODUCED (kusur değil) | Depo zaten düz import kullanıyor (`import axis_v13` vb.); testler `cd AXIS` ile çalışıyor | - |
| G7 | Gemini | high | AXIS/multi_ai_review.py:18 | SECRET regex'i JSON/dict tırnaklı anahtarları, Bearer, AKIA, github_pat_, URL kimlik bilgisini kaçırıyor | CONFIRMED | `repro.py`: `{"password": "hunter2"}`, `"api_key": "sk_live_abc"`, `'password': 'hunter2'`, `{"secret":"s3cr3t"}`, Bearer, AKIA..., `https://u:pw@host`, github_pat_... maskelenmedi; `bundle()` Python kaynağındaki `{"password": "hunter2"}` sözlüğünü olduğu gibi bıraktı. Ayrıca `password = "hunter2"` -> `[REDACTED]"` (artık tırnak). Değerlendirme: yalnızca loopback'e gidiyor ve MULTI_AI_REVIEW.md "tüm sırları yakalama garantisi yok" diyor; yine de diske yazılan rapor ve bundle için gerçek açık, medium-high | Codex C2 (ikinci yarı) |
| G8 | Gemini | high | AXIS/multi_ai_review.py:148 | Serileştirilmiş JSON üzerinde `scrub()` kaçışlı tırnak yüzünden JSON'u bozuyor | CONFIRMED | `repro.py`: açıklama `uses api_key="x" here` -> `scrub(json.dumps(f))` = `...uses [REDACTED]"x\" here"` ; `json.loads` JSONDecodeError; tam `run()` -> FAILED/JSONDecodeError, findings=[] (geçerli inceleme atılıyor). Sır sızıntısı değil, fail-closed; değerlendirme: medium | Codex C2 (ilk yarı) |
| G9 | Gemini | high | AXIS/multi_ai_review.py:48-59 | Kesilme kontrolleri `prompt_eval_count`/`eval_count`/`done_reason` yoksa açık geçiyor | CONFIRMED | `repro.py`: sayaçsız/done_reason'suz, None, string ("99999"), `done_reason=unload`, `prompt_eval_count=0` yanıtlarının hepsi COMPLETED. Not: gerçek Ollama sohbet yanıtı normalde `stop`/`length` döndürür; `unload` iddiası spekülatif, eksik/yanlış tipli metadata gerçek boşluk. Değerlendirme: medium (sessiz kesilme tespiti denemesi hâlâ atlatılabilir) | Codex C1; Claude #1/#2 düzeltmesinin açık kalan kenarı |
| G10 | Gemini | medium | AXIS/multi_ai_review.py:124-126,149-155 | `show` yalnızca üst düzey `remote_host/remote_model` bakıyor; `ValueError` mesajı rapora yazılmıyor (reason `ValueError`) | CONFIRMED (reason kaybı); iç içe alan iddiası doğrulanamadı | `repro.py`: remote_host'lu show -> FAILED, reason yalnızca `ValueError`; `modelfile` içinde uzak FROM -> COMPLETED (yok sayıldı). Gerçek Ollama'nın bu alanları nasıl döndürdüğü test edilmedi. `'cloud'`/`'/'` ad kontrolü zaten ayrı bir kapı. Değerlendirme: low | - |
| G11 | Gemini | medium | AXIS/multi_ai_review.py:64-77 | `bundle()` boş liste, yinelenen yol, normal olmayan dosyaya izin veriyor | CONFIRMED (kısmen) | `repro.py`: `bundle([])` -> `''`; aynı dosya iki kez paketlendi; `dir.py` klasörü -> işlenmemiş PermissionError (run() içinde `directory.mkdir`'dan önce patlıyor). CLI `nargs='+'` boş listeyi engelliyor (yalnızca programatik). Symlink: bu makinede oluşturulamadı (WinError 1314); `resolve()` symlink'i çözüp `is_relative_to` ile reddettiği için kod okumada açık yok. Değerlendirme: low | - |
| G12 | Gemini | medium | AXIS/multi_ai_review.py:35 | `bool` değeri `isinstance(v,int)` geçiyor, limit 1 olur | CONFIRMED (teorik) | `m.context_limit({'model_info':{'x.context_length': True}})` -> `True`. Gerçek Ollama bool döndürmez; değerlendirme: low | - |
| G13 | Gemini | medium | AXIS/multi_ai_review.py:144-146 | Bulgu şeması yalnızca anahtar varlığını doğruluyor; tür/boyut yok | CONFIRMED | `repro.py`: severity sözlük, file liste, line "x", confidence None, explanation 5 ve 200 KB ek alan -> COMPLETED, rapor 200561 bayt. Üst sınır 1 MB yanıt sınırı. Değerlendirme: medium (rapor bütünlüğü); C2'deki "ek alanlar kalıcı" ile birleşir | Codex C2 (ek alan) |
| G14 | Gemini | low | AXIS/multi_ai_review.py:83-89,177 | `show` da 600 sn zaman aşımı alıyor; route allowlist yok; `--timeout` doğrulanmıyor | CONFIRMED | `repro.py` (`OpenerDirector.open` sahte): zaman aşımları tags=5, show=600, bilinmeyen route=5. Route dahili olduğundan allowlist düşük değerli; negatif `--timeout` koddan okunarak doğrulanmıyor | - |
| G15 | Gemini | low | AXIS/multi_ai_review.py:1 | Dosya için birim testi yok | NOT REPRODUCED | `AXIS/test_multi_ai_review.py` var (14 test: truncation, scrub, path, cloud, bağlam). Gemini parça 2'de testleri görmedi (chunk etkisi). Doğru kalan kısım: JSON tırnaklı sırlar test edilmiyor (bkz. G7) | - |
| G16 | Gemini | medium | AXIS/test_multi_ai_review.py:36,45,59,93,107,116,124,134 | Testler canlı depo dosyalarını (`axis_sqlite.py`, `multi_ai_review.py`) kullanıyor | CONFIRMED (kısmen) | Kod okuma. Boyut bağımlılığı doğru; "çalışma dizinine bağlı" iddiası yanlış, çünkü `ROOT = Path(__file__).parent`. Değerlendirme: low | - |
| G17 | Gemini | medium | AXIS/test_multi_ai_review.py:40,53,61,69,78,84,100,108,118,126 | `reports[1]` sabit indeks | CONFIRMED | Kod okuma (satırlar eşleşiyor; ROLES sırasına bağlı). Değerlendirme: low | - |
| G18 | Gemini | medium | AXIS/test_multi_ai_review.py:128-135 | `test_cloud_model_blocked` yalnızca çağrıları doğruluyor, rapor durumunu değil | CONFIRMED | Kod okuma: tek assert `calls == ['tags']`, dönüş değeri atılıyor, tek `:cloud` biçimi. Değerlendirme: low | - |
| G19 | Gemini | medium | AXIS/test_multi_ai_review.py (genel) / multi_ai_review.py:83-93 | Varsayılan `local_api` (loopback, yönlendirme yasağı, boyut sınırı, hata) test edilmiyor | CONFIRMED | Hiçbir test `local_api` çağırmıyor; yalnızca `repro.py` ile zaman aşımı elle ölçüldü | Claude #2'nin genişlemesi |
| G20 | Gemini | low | AXIS/test_multi_ai_review.py:8,42 | Boş olmayan bulgu ve iki farklı model senaryosu test edilmiyor | CONFIRMED | `fake_api` varsayılan içerik `{"findings":[]}`; tek `local:1` modeli | - |
| G21 | Gemini | low | AXIS/test_multi_ai_review.py:23-28 | `test_paths`/`test_redaction` dar: mutlak yol, bundle içi sır, chat payload'ı doğrulanmıyor | CONFIRMED | Kod okuma; ayrıca `test_redaction` yalnızca `api_key="..."` biçimini sınıyor (G7/G8 bu yüzden yakalanmadı) | - |
| G22 | Gemini | low | AXIS/test_multi_ai_review.py:11 | `api.payloads[route]` aynı route'u ezer | CONFIRMED | Kod okuma; mevcut testler tek model/rol kullandığı için şu an etkisiz | - |
| G23 | Gemini | info | AXIS/test_multi_ai_review.py:5 | Kullanılmayan `patch` importu | CONFIRMED | `grep patch` yalnızca import satırını buldu | - |
| G24 | Gemini | medium | AXIS/vector_upgrade.py:139-141 | Zaman aşımında yalnızca docker CLI öldürülüyor, konteyner çalışmaya devam ediyor | CONFIRMED | `repro_docker.py` (verify ile aynı bayraklar, `sleep 90`, `timeout=8`): TimeoutExpired sonrası `docker ps` konteyneri "Up 5 seconds" gösterdi; elle `docker rm -f` ile temizlendi. Pids/bellek/CPU sınırları var ama sonsuz döngülü aday 1 CPU'yu tutabilir | - |
| G25 | Gemini | medium | AXIS/vector_upgrade.py:139 | `--mount` dizgisinde virgüllü Windows yolu ayrıştırmayı bozar | CONFIRMED (teorik) | Kod okuma: yol tırnaklanmıyor. Yol `tempfile.TemporaryDirectory` altından geliyor; kullanıcı adı/TEMP virgül içermedikçe tetiklenmez. Değerlendirme: low | - |
| G26 | Gemini | low | AXIS/vector_upgrade.py:139 | tmpfs'te `nodev` yok; imaj mutable etiket ve `--pull never` yok | NEEDS DECISION | `nodev` yokluğu doğru ama `--cap-drop ALL` ile etkisi düşük; `--pull never`/digest sabitleme ağ/yeniden üretilebilirlik politikası (ENV raporuna göre imaj kullanıcı onayıyla indirildi, digest 5e2bdb1b0d54...) | - |
| G27 | Gemini | low | AXIS/vector_upgrade.py:138 | `r['target']` doğrudan inline betiğe ekleniyor | NOT REPRODUCED | `propose()` -> `safe_target()` yalnızca `ALLOWED={'research_extensions.py','skills_helpers.py'}` kabul ediyor; hedef DB satırından geliyor ve yalnızca `propose` yazıyor. Savunma derinliği önerisi olabilir; DB'ye doğrudan yazan saldırgan senaryosu kapsam dışı | - |
| G28 | Gemini | low | AXIS/test_vector_upgrade_sandbox.py:43-48 | Mount/tmpfs için alt dizge assert'leri; `--rm` ve `size=` yok | CONFIRMED | Kod okuma: `assertIn('readonly', mount)`, `--rm` ve `size=32m` doğrulanmıyor | Claude #2 sonrası düzeltmenin kalan kenarı |
| G29 | Gemini | low | AXIS/test_vector_upgrade_sandbox.py:50-59 | `verify()` için sıfır olmayan çıkış ve TimeoutExpired testi yok | CONFIRMED | Dosyada yalnızca iki test (kilitli komut, Docker yok) | - |
| G30 | Gemini | low | MULTI_AI_REVIEW.md:9 | Örnek komut AXIS/ öneki olmadan dosya adı veriyor | NOT REPRODUCED | Depo kökü benzeri dizinden `multi_ai_review.py axis_sqlite.py` çalıştı (yol `ROOT`'a göre çözülüyor), çıktı klasörü oluştu. Yalnızca belgede "AXIS/ içinden çözülür" notu eklenebilir | - |
| G31 | Gemini | info | MULTI_AI_REVIEW.md:15 | "karakter başına 2,5 token" ifadesi ters; kod geçerli paketleri reddediyor olabilir | CONFIRMED (yalnızca belge) | Kod `CHARS_PER_TOKEN = 2.5` (token başına 2,5 karakter), `prompt_chars/2.5` token hesaplıyor; belgedeki ifade ters yazılmış. Gemini'nin kodun paketleri yanlış reddettiği çıkarımı doğru değil | - |
| G32 | Gemini | high | reports/IMPLEMENTATION_REVIEW.md:11,19 (ve ENVIRONMENT_VERIFICATION_20261109.md son satır) | "commit yapılmadı / inceleme NOT RUN" ifadeleri commit'lenmiş dosyada; iki sağlayıcı kapısı olmadan birleştirme | CONFIRMED (belge bayatlığı); politika kısmı bkz. Merge kapısı | Belgeler 5ee362b'ye commit edilmiş ama "Commit... yapılmadı" diyor. Gerçek yüksek önem belge değil birleştirme politikasıdır. Belgeler için değerlendirme: low | - |
| G33 | Gemini | medium | AXIS_V14_GELISTIRME_PLANI.md:7-12; reports/IMPLEMENTATION_REVIEW.md; reports/GIT_CONNECTION.md; reports/ENVIRONMENT_VERIFICATION_20261109.md | Belgeler arası çelişki: git durumu, qwen3 kurulu mu, test sayısı (48 vs 54) | CONFIRMED | Çapraz okuma: plan "boş master/48 test/indirme durmuş", IMPLEMENTATION "unborn dal/model listesi boş/48+6 test", ENV "qwen3 kuruldu/54 test (50 geçti, 4 atlandı)". Yalnızca GIT_CONNECTION üstüne "supersedes" notu koymuş. Tarihli geçmiş notlar; değerlendirme: low | - |
| G34 | Gemini | medium | reports/ENVIRONMENT_VERIFICATION_20261109.md:3; reports/IMPLEMENTATION_REVIEW.md | Ham kanıt dosyaları commit'te yok; 11/11 Docker ve 50/54 test iddiası rapor setinden doğrulanamaz | NEEDS DECISION | `git ls-files reports` bu dosyaları içermiyor. ENV raporu konumu ("ana checkout'un reports/ klasörü") belirtiyor; kanıtı commit'e almak (temizlenmiş) bir politika kararı | - |
| G35 | Gemini | low | AXIS_V14_GELISTIRME_PLANI.md:12 vs reports/ENVIRONMENT_VERIFICATION_20261109.md:20 | E:/AXIS-Ollama ile E:\AXIS-Models çelişkisi | NOT REPRODUCED | İki farklı şey: uygulama dizini (AXIS-Ollama) ve model deposu (OLLAMA_MODELS=AXIS-Models) | - |
| G36 | Gemini | low | reports/GIT_CONNECTION.md:3; reports/ENVIRONMENT_VERIFICATION_20261109.md | Özel depo URL'si, yerel yollar ve dal adı belgede | NEEDS DECISION | Kimlik bilgisi/anahtar yok; yalnızca depo/yol bilgisi, depo özel. Dışa açılırsa temizleme kararı | - |
| C1 | Codex | medium | AXIS/multi_ai_review.py:48-59 | Kesilme kontrolleri eksik/yanlış tipli metadata'da açık geçiyor | DUPLICATE (G9) | G9 ile aynı yeniden üretim | G9; Gemini bağımsız onaylıyor |
| C2 | Codex | medium | AXIS/multi_ai_review.py:18,148 | `scrub(json.dumps(...))` JSON'u bozuyor; `{"password":...}` gibi yapılandırılmış alanlar kalıcı yazılıyor | DUPLICATE (G8, G7, G13) | `repro.py`: `explanation` içinde `api_key="x"` -> FAILED/JSONDecodeError; ek alan `{"password":"hunter2"}` -> COMPLETED ve rapor çıktısında `hunter2` var (True) | G8, G7, G13 |

Claude raporuyla örtüşmeyen açık maddeler (doğrulanmadı, yeniden değerlendirilmedi): Claude #6 (`'/' in model` ad alanlı yerel modelleri reddediyor, güvenli yönde) ve Claude #4 (çıktı klasörü ignore'u; `.gitignore` şimdi `reports/[0-9]*T[0-9]*-*/` içeriyor, bu doğrulayıcı scratch'te çıktı klasörünü gözlemledi). Claude #3 ve #1 düzeltmeleri bu inceleme turunda G9'un kalan kenarıyla ilgili.

## Önerilen düzeltmeler (öncelik sırasıyla)

Hiçbiri uygulanmadı.

1. G9 / C1 (kesilme kontrolü kapalı başarısız olmalı): `check_not_truncated` ve `check_output_complete` içinde `prompt_eval_count` ve `eval_count` için `isinstance(x, int) and not isinstance(x, bool) and x > 0` zorunlu kıl, değilse `ContextTruncated`/`OutputTruncated` (ya da yeni `MetadataMissing`) fırlat; `done_reason` için `== 'stop'` iste. `test_multi_ai_review.py`'a eksik, None, string, `done_reason=None` ve `unload` testleri ekle (`fake_api` bu alanları atlayabilmeli).
2. G8 / C2 (scrub JSON'u bozuyor): `scrub`'u serileştirilmiş metne değil ayrıştırılmış `findings` ağacına uygula: sözlük/liste üzerinde özyinelemeli, tüm str değerlere ve anahtar adı `password|secret|token|api_key` olan alanların değerine `[REDACTED]`. `json.loads(scrub(json.dumps(...)))` satırını bununla değiştir. Test: açıklama `api_key="x"` içerirken COMPLETED kalmalı ve `x` rapora yazılmamalı.
3. G7 (SECRET regex kapsamı): anahtar ile ayırıcı arasında isteğe bağlı tırnak kabul et (`(?:api[_-]?key|password|secret|token)["']?\s*[=:]\s*["']?[^\s"',;}\]]+`), Bearer, `AKIA[0-9A-Z]{16}`, `github_pat_...`, `://kullanıcı:parola@` desenleri ekle. Artık kalan tırnağı (`[REDACTED]"`) temizle. Testlere JSON ve dict tırnaklı örnekler ekle; MULTI_AI_REVIEW.md uyarısı kalsın.
4. G13 (bulgu şeması): `severity/file/confidence/explanation` için `str`, `line` için `None` veya (bool olmayan) `int`; alan başı uzunluk sınırı (örn. 4000) ve bilinmeyen anahtarların atılması. C2'deki ek alan kalıcılığını da kapatır.
5. G24 (zaman aşımında konteyner): `--name axis-verify-<uid>` ve `--init` ekle; `except subprocess.TimeoutExpired` içinde `subprocess.run(['docker','rm','-f',name], capture_output=True, timeout=15)`. Test: TimeoutExpired mock'u `docker rm -f` çağrısını doğrulamalı (aynı zamanda G29'u kapatır).
6. G10 (reason mesajı): politika ihlallerini ayrı bir `PolicyViolation` istisnasıyla `reason`'da koru; `details`/`modelfile` kontrolü gerçek Ollama çıktısıyla doğrulandıktan sonra eklensin.
7. G1 (başlatma hatasında kapatma, düşük): 8 fabrikada `connect` sonrası ayarları `try: ... except: db.close(); raise` ile sar.
8. G11 / G12 / G14 (hızlı sertleştirme): `bundle()` içinde boş liste, yinelenen ad ve `path.is_file()` reddi; `context_limit` içinde bool dışla; `local_api` içinde zaman aşımını yalnızca `chat` için 600 sn tut (`show`/`tags` 5 sn).
9. Testler (G16-G23, G28, G29, G19): rol adına göre rapor bulma yardımcısı, `local_api` için `urlopen` mock testi, boş olmayan bulgu ve iki model senaryosu, `fake_api` çağrı listesi, sandbox testinde `--rm`/`size=` ve hata/zaman aşımı yolları.
10. Belgeler (G31, G32, G33): MULTI_AI_REVIEW.md'de "token başına 2,5 karakter" düzelt; IMPLEMENTATION_REVIEW.md ve plan belgelerine tarihli/yerine geçen-not başlığı veya güncel durum ekle (GIT_CONNECTION.md örneği gibi).
11. G4 (düşük): `*.py[cod]` geri koy ve `*.db*`/`*.sqlite*` yerine açık sonekler kullan.

## Çözülmemiş ayrılıklar

- Gemini (G7/G8/G9 high) ile Codex (C1/C2 medium) aynı kusurları farklı önemde değerlendiriyor. Ben üçünü de yeniden ürettim; etkileri farklı: G9 sessiz kesilmiş bir incelemeyi COMPLETED gösterir (inceleme kapısı güveni), G8 geçerli incelemeyi FAILED yapar (kullanılabilirlik, sızıntı yok), G7 sır maskelemede gerçek boşluk. Hepsi yerel loopback'te kalıyor; "high" önemini kullanıcı belirlemeli.
- NOT REPRODUCED: G2 (with dışı/yeniden kullanım yok), G5, G6, G15 (testler var; Gemini parçada görmedi), G27 (hedef `ALLOWED` ile sınırlı), G30 (komut çalışıyor), G35.
- Kısmen doğru/yanlış yönlendirilmiş: G10 iç içe alan iddiası (gerçek Ollama ile test edilmedi), G16 CWD iddiası (yanlış), G31 çıkarımı (yanlış, yalnızca belge ifadesi ters).
- NEEDS DECISION: G26 (`--pull never`, digest sabitleme), G34 (kanıt dosyalarını commit'e alma), G36 (URL/yol ifşası).
- Gemini yalnızca parça bağlamıyla baktı (araç/dosya erişimi yok, hiçbir şey çalıştırmadı); Codex tam diff gördü ama yazar. İkisinin ortak kesiştiği bulgular (G8/G9) yazar yanlılığı olmadan tekrarlanıyor.
- G1 için Gemini "medium"; yeniden üretimde CPython ref sayımı çoğu durumda bağlantıyı bıraktığı için pratik etki düşük ve değişiklikten önce de vardı.

## Merge kapısı

AGENTS.md maddeleri 3, 5, 7, 9'a göre, olgusal durum:

- Yüksek etkili değişiklik (ağ, güvenlik) için iki ayrı sağlayıcının bağımsız incelemesi gerekiyor.
- Claude: yalnızca Codex'in yazdığı parçalar (SQLite, multi_ai_review ve testleri) için bağımsız. Claude `--memory-swap`, import taşıma, `.gitignore` `!.env.example`, ENV raporu ve 5ee362b'deki `num_ctx`/kesilme düzeltmesini kendisi yazdı; bunlar için Claude bağımsız değil. Ayrıca Claude'un yazılı incelemesi 2c3f099 üzerindeydi, 5ee362b için yeniden yapılmadı.
- Gemini: yanıt aldı (5/5 parça COMPLETED), ancak diff parça parça, elle yeniden yazılarak ve satır içi gönderildi; araç/dosya erişimi ve test çalıştırma yok; yeniden yazılan metin kayıtlı olmadığı için tam fidelity doğrulanamadı (kod farkı bulunmadı, dolaylı kanıt). AGENTS.md madde 5 "aynı sınırlı diff" ile uyumu parçalı gönderim yüzünden tartışmalı.
- Codex: yazar; bağımsız değil.
- qwen3:8b yerel model: NOT RUN.
- Parça bazlı formel durum: Codex-yazımı kodda Claude + Gemini = iki bağımsız sağlayıcı; Claude-yazımı parçalarda Gemini (+ yazar olmayan Codex) bağımsız. AGENTS.md'nin bu parçalı/dolaylı durumu karşılayıp karşılamadığı bir karardır; doğrulayıcı bunu çözmüyor. Yani koşulun karşılandığı iddia edilemez, yalnızca formel olarak mümkün görünüyor.

Açık engelleyici maddeler (düzeltilmeden birleştirme önerilmez):
1. G9 / C1: kesilme tespiti eksik metadata'da açık geçiyor (inceleme kapısı güvenilirliği; Claude'un kendi raporu bu aracın çıktısını kapı olarak kullanmama koşulu koymuştu).
2. G8 / C2: scrub JSON'u bozuyor, geçerli incelemeyi FAILED yapıyor.
3. G7: sır maskeleme JSON/dict tırnaklı anahtarları kaçırıyor; yapılandırılmış ek alanlar (G13) kalıcı yazılıyor.
4. G24: Docker doğrulama zaman aşımında konteyner çalışmaya devam ediyor (vector_upgrade yolu).
5. İki bağımsız sağlayıcı koşulunun yukarıdaki parçalı durumla karşılanıp karşılanmadığına kullanıcı kararı; qwen3 NOT RUN.
Diğer tüm CONFIRMED maddeler düşük/orta etkili (test, belge, sertleştirme) ve engelleyici sayılmıyor.

## Ek: Codex modelinin doğrulanması (2026-11-10)
Codex oturum kayıtlarına göre Codex yazar görüşü (21:52:57Z) ve G24 Docker düzeltmesini üreten çağrılar (22:08Z) `gpt-6.1-sol` (OpenAI) ile çalıştı. GLM/Ollama bulutu kullanılmadı.

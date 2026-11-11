# VECTOR Brain V5

This extends V4 with (1) an interactive visualization of a small neural network's weights (this untrained V5 example has been replaced; see README_V6.md); (2) Docker-based isolated syntax/unittest verification; (3) explicit human-approved, allowlisted Python module updates with backups and rollback.

## Windows 11

1. Install Python 3.11+, Docker Desktop with Linux containers, and optionally Ollama for the V4 features.
2. Open PowerShell in this directory: `py -m pip install -r requirements.txt`.
3. PyTorch is optional and not needed for the 3D view (see README_V6.md).
4. For isolated tests, start Docker Desktop and pre-pull `docker pull python:3.12-slim` while online.
5. Run `py server.py` and visit `http://127.0.0.1:8765`.
6. Click **Gerçek sinir ağı** to view weights, rotate/zoom. Green lines = positive weights; pink = negative; thickness = magnitude.
7. In Self-Evolution V5, submit a Python module change, inspect diff, run Docker test, approve explicitly, then restart VECTOR. Rollback requires separate confirmation and restart.

## Important limitations

- The 3D neural view is a small trained XOR network (2→8→1), not Qwen3's billions of weights. The former untrained 4→8→6→2 PyTorch example no longer exists. See README_V6.md.
- Docker isolation is defense in depth, **not an absolute security guarantee**. Docker Desktop must be trusted and patched. No host-side execution fallback is allowed.
- The Docker test currently checks Python syntax and discovers any `test_*.py` in the isolated staging directory. No behavior tests are automatically generated; therefore a passing result does **not** establish functional correctness. Review is mandatory.
- Only `vector_intelligence.py`, `research_extensions.py`, and `skills_helpers.py` are updateable. `server.py`, `vector_upgrade.py`, `self_evolution.py` and permission code are deliberately protected.
- Updates do not hot-reload; restart is required. Rollback restores only the target file, not external side effects or database migrations.
- LLM autonomous core proposal generation, real Qwen3 weight/activation visualization, and complete secure production-grade self-modification are **not implemented**.
- The previous V4 features may require network access, PyMuPDF, and a running Ollama model.

Run tests: `py -m unittest test_server.py test_v5.py -v`.

## Otomatik çekirdek güncelleme (2026-11-10)

Kullanıcının açık kararıyla (2026-11-10) çekirdek güncellemeler artık **otomatik uygulanır** — ama yalnızca izole Docker testi PASS olduğunda. Yukarıdaki "approve explicitly" adımı ve "Only … are updateable" listesi bu bölümle değişmiştir.

- **Akış:** `propose()` → arka planda `verify()` (Docker, ağsız, salt-okunur, değişmedi) → yalnızca PASS ise mevcut `decide(id, 'approve', 'ONAYLIYORUM')` yolu çağrılır. Bu yol taze bir Docker testi daha çalıştırır, özeti (digest) yeniden doğrular, dosyayı atomik olarak yazar ve yedek alır. FAIL veya BLOCKED (Docker yok) ise hiçbir şey uygulanmaz; öneri raporuyla birlikte bekler ve arayüzden reddedilebilir.
- **Kapsam:** AXIS klasörünün üst düzeyindeki her `*.py` modülü, şunlar **hariç** (korunan liste): `vector_upgrade.py`, `local_models.py`, `server.py`, `axis_sqlite.py`, tüm `test_*.py` dosyaları, `.py` olmayan her dosya (`index.html` onay arayüzünü taşır) ve klasör dışındaki her yol (yol geçişi ve sembolik bağlantılar reddedilir).
- **Korunan listenin nedeni:** hatalı bir otomatik güncelleme test/geri alma hattını, yalnızca-yerel model korumasını, HTTP köken (Origin) denetimlerini ve onay uç noktalarını asla devre dışı bırakamasın; bir güncelleme kendi testlerini de düzenleyemesin.
- **Kapatma anahtarı:** sunucuyu `AXIS_AUTO_APPLY=0` (ya da `false` / `off`) ile başlat. Varsayılan: açık. Kapalıyken öneriler bekler; tek tek uygulama API üzerinden (`POST /api/upgrade-decision`, `ONAYLIYORUM`) çalışmaya devam eder.
- **Denetim kaydı:** her otomatik uygulama ve test başarısızlığı `central_brain` deneyimlerine (`agent='auto_upgrade'`) ve `upgrades.sqlite3` içindeki `auto_events` tablosuna yazılır; arayüzde "Otomatik uygulandı: <hedef> — <açıklama>" olarak görünür.
- **Geri alma:** her otomatik uygulanan öğede "Geri al" (onay penceresi + `GERI_AL`) kalır. Uygulama ve geri alma, sunucu yeniden başlatılınca etkin olur ("yeniden başlatma gerekli").
- **Değişmeyenler:** beceri dosyaları, ajan rolleri ve öğrenilmiş beceriler hâlâ elle onay ister. Docker testi yalnızca sözdizimi, AST sözleşmesi ve verilen davranış testlerini çalıştırır; PASS işlevsel doğruluğun kanıtı değildir.
## Literatür kaynakları

- Araştırma önce OpenAlex'i kullanır. OpenAlex anahtarsız kullanımda küçük bir günlük kota uygular; kota dolunca (HTTP 429) iş otomatik olarak arXiv API'sine (ücretsiz, anahtarsız) geçer. İş ayrıntısında hangi kaynağın kullanıldığı yazar (`OpenAlex: …` / `arXiv: … · OpenAlex günlük ücretsiz kotası doldu → arXiv kullanıldı`).
- İsteğe bağlı: ücretsiz bir OpenAlex anahtarı `OPENALEX_API_KEY` ortam değişkeniyle verilirse istekte kullanılır. Anahtar depoya yazılmaz.
- arXiv kayıtlarında kavram etiketleri arXiv kategorileridir (ör. `cs.LG`); doğrulanmış çıkarım değildir.
- Araştırma tamamlanınca ya da başarısız olunca sonuç sohbete de yazılır.

## Soru-cevap: hibrit arama (RAG)

- Soru sorulduğunda bellek üç yoldan aranır ve sonuçlar karşılıklı sıra füzyonu (RRF) ile birleştirilir: SQLite FTS5 tam metin araması (BM25, başlık ağırlıklı, Türkçe aksan katlamalı), yerel gömme modeliyle anlamsal arama (`axis_memory`, Ollama `bge-m3`, çok dilli: Türkçe soru İngilizce özeti bulur; PDF bölümleri de buradan gelir) ve eski Türkçe→İngilizce anahtar kelime eşleyicisi.
- Model en fazla 8 kaydı numaralı olarak görür ve yanıtta `[1]`, `[2]` diye atıf yapar; arayüz numaralı kaynakları, ağda gösterme düğmesini ve yalnızca http(s) bağlantılarını gösterir.
- **Tek gömme deposu:** vektörler yalnızca `axis_memory.sqlite3` dosyasındadır (`axis_memory.py`; bilgi ağı düğümleri, makale özetleri ve PDF bölümleri). Onu tek bir arka plan işçisi (`axis-memory-index`) günceller: sunucu açılınca, her araştırma/PDF sonrasında ve 10 dakikada bir. İşçi her turda silinmiş düğümlerin kayıtlarını da depodan temizler (PDF bölümleri, kaynak PDF'i silinmedikçe kalır; boş bir vector.db depoyu silmez). Her soru için sorgu yalnızca bir kez gömülür ve depo bir kez taranır.
- `vector.rag.sqlite3` (vector.db'nin yanında, git'e girmez) artık yalnızca FTS5 tam metin dizinini tutar. Silinirse vector.db'den yeniden kurulur; her soruda özet karşılaştırmasıyla güncellenir (~0,03 sn). İçindeki eski `embeddings` tablosu (kaldırılan `rag_embed.py`'nin ikinci gömme deposu) kullanılmıyor; AXIS ona dokunmaz. İstersen sunucu kapalıyken `DROP TABLE embeddings; VACUUM;` ile ya da dosyayı silerek yer açabilirsin.
- Anlamsal isabetler RRF'ye şöyle girer: düğüm → `node:<id>` (makale düğümü, kanıt bağıyla `src:<kaynak>` kaydına eşlenir; böylece URL/yıl korunur ve aynı makale üç listede tek belge sayılır), PDF bölümü → `chunk:<id>` (numaralı kayıt, en fazla 700 karakter). Yanıttaki `semantic` alanı, modele giden kayıtlardan en az birinin gömme aramasıyla bulunduğunu söyler.
- Durum: Sistem → «Anlamsal dizin», `GET /api/rag-status` (`embedded_docs`/`memory_items`/`pending`/`available` axis_memory'den, `fts_docs` tam metin dizininden). `POST /api/memory-backfill`, arka plan işçisi o anda çalışıyorsa aynı kayıtları ikinci kez gömmek yerine `busy: true` döner.
- Gömme modeli `AXIS_EMBED_MODEL` ile değiştirilebilir; model değişince vektörler yeniden üretilir. Bulut modelleri reddedilir; tüm istekler 127.0.0.1 üzerinden gider. Ollama kapalıysa arama tam metin + anahtar kelimeyle sürer.

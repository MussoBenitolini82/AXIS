# Ortam doğrulaması — 9 Kasım 2026 (yeniden başlatma sonrası)

Ham kanıt dosyaları ana checkout'un reports/ klasöründe: docker_isolation_test.py, docker-isolation-20261109.json, model_smoke_test.py, model-response-qwen3-8b-20261109.json, ollama-pull-resume.log.

## WSL / Docker
- Kullanıcı "Sanal Makine Platformu" özelliğini etkinleştirip yeniden başlattı. WSL2 çalışıyor; tek dağıtım `docker-desktop` (Docker Desktop tarafından oluşturuldu, WSL 2).
- Docker Engine 29.9.2, çekirdek 6.18.33.2-microsoft-standard-WSL2. CLI PATH üzerinde: E:\AXIS-Docker-App\resources\bin\docker.exe.
- Kullanıcı onayıyla `python:3.12-slim` indirildi (sha256:5e2bdb1b0d54…).

## Docker izolasyon testleri
AXIS/vector_upgrade.py verify() ile birebir aynı bayraklar kullanıldı. 11/11 geçti.
- Olumlu: /work okunur, uid/gid 65534, /tmp yazılabilir.
- Olumsuz: ağ yok, DNS yok, /work ve kök dosya sistemi salt okunur, /tmp noexec, pids 64 sınırı, 512m bellek sınırı (OOM, rc=137), ham soket yok.
- Host bind dizini değişmedi; konteynerden host yoluna yazma girişimi host'ta dosya oluşturmadı.
- Docker yoksa vector_upgrade.verify() "BLOCKED" döndürüyor, kod host'ta çalıştırılmıyor (kod incelemesi).

Bulgu (düşük): `--memory-swap` verilmediği için cgroup memory.swap.max = 512 MB; konteyner toplamda ~1 GB kullanabiliyordu. DÜZELTİLDİ: vector_upgrade.py komutuna `--memory-swap 512m` eklendi. Doğrulama: memory.swap.max = 0; 200 MB çalıştı, 600 MB rc=137 ile sonlandı.

## Ollama / qwen3:8b
- Ollama 0.40.15, OLLAMA_MODELS=E:\AXIS-Models. İndirme mevcut parçalardan sürdürüldü, sha256 doğrulandı.
- Model: qwen3:8b, digest 500a1f067a9f…, 8.2B, Q4_K_M.
- Gerçek yanıt: `{"toplam": 42, "dil": "Türkçe"}`; iki kontrol de doğru. Yükleme 44 s, toplam 79 s.

## Testler
Python 3.12.10, kaynak kopyasında: 54 test, 50 geçti, 4 atlandı (torch kurulu değil).

## Kaynak incelemesi düzeltmeleri (worktree: claude/determined-elgamal-c2a94f)
Ana checkout'taki kaydedilmemiş içerik değişiklikleri ve yeni dosyalar worktree'ye kopyalandı; ana checkout değiştirilmedi.
- `from axis_sqlite import ClosingConnection` 7 modülde docstring'in altına taşındı (server.py'de docstring yok). Tüm modüllerde `__doc__` dolu.
- `.gitignore`: `.env*` altına `!.env.example` eklendi; `.env`, `.env.local` yok sayılmaya devam ediyor.
- Düzeltmelerden sonra testler: 54 test, 50 geçti, 4 atlandı (torch yok).

## İnceleme durumu
Bağımsız sağlayıcı incelemesi: NOT RUN. Tek yerel model (qwen3:8b) mevcut; AGENTS.md uyarınca iki farklı sağlayıcı gerekir.
Commit, push veya main birleştirmesi yapılmadı.

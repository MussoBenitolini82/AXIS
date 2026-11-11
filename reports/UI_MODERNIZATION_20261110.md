# AXIS koyu arayüz geliştirmesi — 2026-11-10

Dal: `axis-updates-20261110`. Temel: `368baf4`. Değişiklikler yerel; commit, push veya main birleştirmesi yapılmadı.

## Değişiklikler
- `AXIS/index.html`: koyu varsayılan tema, karşılama kartları, başlıklar, komut alanı ve panel erişilebilirlik durumu.
- `AXIS/static/app.css`: antrasit/lacivert zemin, lavanta/turkuaz vurgular, ferah tipografi, kartlar ve mobil yerleşim. Açık tema tercihi ve azaltılmış hareket desteği korunur.
- `AXIS/test_ui_commands.py`: gerçek JavaScript işlevlerini Node ile çalıştıran dört regresyon testi.
- Önceki Windows düzeltmeleri, yerel test değişiklikleri ve kullanıcı verileri korunmuştur. Çalışan eski kurulumun dosyaları değiştirilmedi.

## Hata bulgusu ve düzeltme
Kullanıcının ekran görüntüsünde OpenAlex araştırmaları `HTTP Error 429: Too Many Requests` ile başarısız. Bu, dış servisin istek sınırı yanıtıdır; görüntüden sınırın türü veya süresi belirlenemez.

Kodda Enter üzerinden gönderim, devre dışı gönder düğmesine rağmen tekrar çalışabiliyordu. Gönderim kilidi eklendi; beklerken yazılan yeni metnin silinmesi önlendi. Aynı sayfada bekleyen veya çalıştığı bilinen aynı konu araştırmasının yeniden gönderilmesi engellendi. HTTP 429, açıklayıcı Türkçe mesajla gösterilir; geçmiş kayıtlar silinmez.

Bu koruma OpenAlex kotasını kaldırmaz; farklı sekmeler, istemciler veya yeniden başlatmalar arasında sunucu düzeyinde sınırlama sağlamaz. Harici servise yeni araştırma isteği gönderilmedi.

## Ajanlar ve inceleme
- `dark_styles`: CSS geliştirmesi.
- `ui_shell`: HTML/JavaScript geliştirmesi ve regresyon testleri.
- `ui_review`: salt okunur kod incelemesi; yeni engelleyici bulgu yok.
- Ana Codex ajanı: entegrasyon, fark kontrolü, tüm testler ve rapor.

Bunlar Codex alt ajanlarıdır; ayrı model sağlayıcılarıyla bağımsız inceleme olarak sunulmaz. Claude/Gemini/Ollama sağlayıcı incelemesi: **NOT RUN**. Bu turda paket, model veya ücretli API kullanılmadı/kurulmadı.

## Doğrulama
`AXIS_AUTO_APPLY=0` ile `python -m unittest discover -p 'test*.py' -v`: **179 test, 23.624 saniye, OK**, çıkış kodu 0. Çıktı: çalışma ağacındaki `ui-tests.log` (Git tarafından hariç tutulur).

Yeni testler: inline JavaScript sözdizimi; eşzamanlı ve çalışan konu tekrarlarının engellenmesi; 429/ağ hatası sonrası kilidin bırakılması; Enter tekrarının engellenmesi ve yeni taslağın korunması. `git diff --check`: temiz.

## Kalanlar
- Tarayıcı görsel/etkileşim doğrulaması: **NOT RUN**. Headless Edge başlatma otomatik güvenlik denetimince engellendi; ayrıntılı gerekçe verilmedi. Önizleme için açılan geçici statik sunucu durduruldu.
- Önceden var olan mobil erişilebilirlik sorunu: küçültülmüş inspector CSS dönüşümüyle gizleniyor, içerideki kontroller klavye odağı alabiliyor. Bu turda değiştirilmedi.
- Güncel arayüz bu çalışma ağacında bulunur; çalışan eski sunucuya otomatik aktarılmadı.
- GitHub'a gönderme veya main'e birleştirme için kullanıcı onayı gereklidir.

# AXIS V14 geliştirme planı

9 Kasım 2026. Kaynak: yerel Codex devir notları (CODEX_DEVIR_NOTLARI.md) ve bu oturumdaki kaynak/test incelemesi. Devir notları geçmiş durumun özetidir; yeni bir sistem değişikliği veya GitHub gönderimi için izin yerine geçmez.

## Doğrulanmış durum

- Bu yeni çalışma alanında kaynak checkout'u yok; Git boş master dalında, henüz commit yok.
- Çalışan kaynak görüntüsü ve Windows düzeltmeleri önceki yerel Codex çalışma alanının installed/AXIS klasöründedir.
- Kaynak tabanı db2438d; son doğrulanan GitHub main cb46e249babdeb9cfda4fcfc66cced6b6b9ae636. Uzak fark yalnızca AGENTS.md eklenmesidir.
- SQLite bağlantıları bağlam çıkışında kapanacak şekilde sekiz modül düzeltildi. axis_sqlite.py ve iki regresyon testi korunmalıdır.
- Son çalıştırma: Python 3.12, `python -m unittest discover -p 'test*.py' -v`; 48 test geçti, atlanan yok. Bu belge hazırlanırken test tekrar çalıştırılmadı; önceki tests-review.log doğrulandı.
- Ollama E:/AXIS-Ollama, Docker E:/AXIS-Docker-App üzerine kurulmuştur. qwen3:8b indirmesi bağlantı kesilmesi ve deneme sınırı nedeniyle durmuş; gerçek yanıt testi yok. Docker motoru ve izolasyon doğrulaması için WSL yeniden başlatma adımı bekliyor.
- Android / AXISANDR askıda. GitHub'a gönderim yapılmadı. Bağımsız sağlayıcı incelemesi: NOT RUN.

## Uygulama sırası ve kabul ölçütleri

1. **Kaynak ve veri koruma:** Geçerli Git checkout'u oluştur; mevcut SQLite düzeltmelerini diff ile axis-windows-fixes dalına ayır. Çalışan kurulum ve veritabanlarını yerinde koru. Kaynak, test ve belge dışındaki yerel dosyaları açıkça dışla. Kabul: taban SHA, incelenebilir diff, veri/venv/model içermeyen değişiklik listesi ve 48 geçen test. V14 için ayrı özellik dalı kullan.
2. **Uçtan uca ortam doğrulaması:** Önceden onaylanmış model indirmesine mevcut parçalardan devam et; gerçek AXIS yanıtını kaydet. Yeniden başlatma için ayrıca onay al. Docker testlerini geçici verilerle, ağ kapalı, salt okunur dosya sistemi ve kaynak sınırlarıyla çalıştır. Kabul: gerçek yanıt, olumlu/olumsuz Docker testleri ve başarısızlıkta host üzerinde çalıştırma yapılmadığının doğrulanması.
3. **V14 ajan gözlemlenebilirliği:** Her görev/aşama için ortak kimlik, zaman, süre, gerçek sağlayıcı/model, durum ve hata kodu tanımla. Olayları gerçekleşen çağrıların çevresinde üret; çalışmayan aşamayı başarılı sayma. V13 API uyumluluğunu koru. Kabul: başarı, hata, zaman aşımı ve kısmi başarının API ve arayüzde doğru görünmesi; günlüklerde sır bulunmaması.
4. **Gerçek öğrenme kayıtları:** Öneri, denenmiş sonuç ve onaylanmış ders durumlarını ayır. Dersleri kaynak olay ve test kanıtlarına bağla; yinelenen kayıtları önle. Mevcut SQLite şemaları için veri kaybetmeyen geçiş ve geri dönüş tasarla. Kabul: başarısız veya kanıtsız olaydan doğrulanmış ders üretilmemesi; eski verinin okunabilmesi.
5. **Onaylı iyileştirme döngüsü:** Öneri → diff → bağımsız inceleme → izole test → kullanıcı onayı → uygulama → geri alma akışını görünür kıl. Onayı tam diff hash'ine bağla; değişen kod önceki onayı geçersiz kılsın. AGENTS.md uyarınca yüksek etkili değişiklikleri yalnızca yetkilendirilmiş iki farklı sağlayıcıyla incelet; bulunamazsa NOT RUN yaz. Kabul: onaysız uygulama yok, değişmiş kod için eski onay kabul edilmiyor, geri alma testleri geçiyor.
6. **3D öğrenme grafiği:** Mevcut olay/ajan/ders grafiğinden beslenen 3D görünüm ekle; demo veriyi gerçek veriden açıkça ayır. Görev/durum/zaman filtreleri ve olay ayrıntıları sun. 3D desteklenmiyorsa 2D görünümü koru. Kabul: yalnızca gerçek kayıtlara bağlı düğümler/kenarlar, bozuk ilişki olmaması ve büyük grafikte sınırlı veri yükleme.
7. **Teslim ve yayın kapısı:** Tam Python testi, API sınır testleri ve gerçek ortam kontrollerinin sonuçlarını raporla. Gerçek inceleyicileri, çözülmeyen bulguları, veri geçiş etkilerini ve geri dönüş yolunu belirt. GitHub push veya main merge öncesinde açık kullanıcı onayı al.

## Kapsam sınırı

Android/APK, kontrolsüz öz-değişiklik, kendiliğinden paket kurma ve onaysız dış sağlayıcı etkinleştirme bu planın kapsamında değildir. İlk geliştirme hedefi güvenilir V13 tabanı ve doğru gözlemlenebilirliktir; sonraki aşamalar bunların kabul ölçütlerine bağlıdır.

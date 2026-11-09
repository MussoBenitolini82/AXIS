# VECTOR V10 — Central Brain Learning Engine

Bu sürüm V9 üzerine kuruludur. Ajan olayları `central_brain.sqlite3` içinde saklanır. Araştırma, ajan tarama, çok ajanlı kod önerme ve paralel araç çağrıları ortak hafızaya deneyim logları gönderir. Başarılı deneyimler beceri önerisine kanıt olabilir. Kullanıcı onayı olmadan beceri etkinleşmez. Beceri grafiği mevcut 3D arayüzde gösterilir.

## Önemli sınırlar
- Bu sürümde öğrenme, kaynaklı deneyim kaydı ve onaylı iş akışı tanımıdır; Qwen model ağırlıkları değişmez.
- Yeni beceriler onaylandıktan sonra katalogda kayıtlıdır; otomatik yürütücü henüz bağlı değildir.
- `discover` yalnızca tekrar eden başarılı araç kullanımını bulur, otonom mantıksal genelleme yapmaz.
- Ajan logları tüm geçmiş olayları kapsamaz; V10'daki bağlanan yolları kapsar.
- Uçtan uca Windows/Ollama/Docker doğrulaması ayrıca yapılmalıdır.

## Kurulum
KURULUM.bat ve BASLAT_VECTOR.bat önceki gibi. Test: `cd VECTOR && py -m unittest discover -v`.

## API
GET `/api/brain-experiences`, `/api/brain-skills`, `/api/brain-discover`, `/api/brain-graph`; POST `/api/brain-log`, `/api/brain-propose`, `/api/brain-decision`. `brain-log` sadece yerel güvenilir ajan entegrasyonu içindir; internete açmayın.
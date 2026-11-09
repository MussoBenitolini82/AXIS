# AXIS V12 — Central Brain Learning & Recovery

V11 üzerine eklenenler:
- Ajanların görev bazlı, JSON biçiminde standart olay kaydı (`axis_learning.py`).
- Başarılı ve başarısız tekrarlanan örüntülerden **kanıt ID’leriyle** ders çıkarma.
- İki veya daha fazla **onaylı** salt-okunur beceriyi birleştirerek **yeniden onay gerektiren** beceri önerisi.
- Onaylı salt-okunur beceriler için en fazla iki denemeli yürütme; her denemede log.
- `/api/axis-events`, `/api/axis-lessons`, `/api/axis-record`, `/api/axis-learn`, `/api/axis-compose`, `/api/axis-recover`.

**Sınırlar:** Eski ajanların tüm işlemleri otomatik olarak bu yeni olay veritabanına aktarılmaz. Yeni ajanlar `/api/axis-record` çağırmalıdır. Başarısız denemelerde düzeltme **otomatik kod yazma** değil, sınırlı yeniden denemedir. Gerçek model kataloğundan otomatik indirme yoktur. LLM ağırlıkları güncellenmez. Her beceri önerisi insan onayı gerektirir. GPT-6.1 Sol bağımsız incelemesi yapılmamıştır.

Kurulum: `KUR_AXIS.bat`, sonra `BASLAT_AXIS.bat`. Test: `cd AXIS && py -m unittest discover -p 'test_*.py'`.
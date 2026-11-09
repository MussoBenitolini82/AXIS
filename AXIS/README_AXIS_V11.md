# AXIS V11 — Central Brain Skill Executor

VECTOR projesinin yeni adı **AXIS**. V10 kod tabanı korunur; eski modül dosya adları uyumluluk için değişmedi.

## Yeni işlev
- Ajanların başarılı deneyimlerinden oluşturulan ve **ONAYLIYORUM** ile onaylanan iş akışlarını çalıştırır.
- Güvenli araç listesi: `count_nodes`, `list_recent_research`, `search_memory`.
- Her adımı ana beyine kaydeder; çalıştırma geçmişi `axis_runs.sqlite3` veritabanında tutulur.
- Başarısız adımda durur, sonucu ve hatayı kaydeder.
- Ağ erişimi, yeni kod yürütme, model indirme ve dosya değiştirme bu yürütücüde **yoktur**.
- Eski onaylı beceriler içinde güvenli olmayan adım varsa çalıştırma reddedilir.

## Kurulum
1. Python 3.11/3.12, Ollama ve (kod testleri için) Docker Desktop kur.
2. `KUR_AXIS.bat` çalıştır; sonra `BASLAT_AXIS.bat` aç.
3. `http://127.0.0.1:8765` adresine git.
4. V10 panelinden en az iki başarılı deneyime dayalı bir beceri öner, onayla.
5. V11 panelinden çalıştır.

## Test
`cd AXIS && py -m unittest discover -p 'test*.py'` (bazı testler PyTorch gerektirir).

## Sınırlar
Bu sürüm genel amaçlı otonom ajan veya kendi kendine LLM ağırlığı güncelleyen bir sistem değildir. Onaylı beceri çalıştırıcısı yalnızca üç salt-okunur aracı destekler. Yerel Windows + Ollama + Docker uçtan uca testi kullanıcı ortamında gereklidir. GPT-6.1 Sol ile bağımsız inceleme yapılmadı.
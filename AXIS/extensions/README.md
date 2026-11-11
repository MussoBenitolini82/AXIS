# AXIS extensions

Bu klasör, `vector_upgrade` üzerinden **otomatik uygulanabilen tek hedef** olan `extensions/<modül>.py`
dosyaları içindir (alt klasör yok, `test` ile başlayan ad yok, sembolik bağlantı yok).

- Bir öneri ancak izole Docker doğrulaması (sözleşme + davranış testleri + deponun kendi test paketi) PASS
  verirse `decide()` yolundan atomik olarak yazılır; yedeklenir ve `GERI_AL` ile geri alınabilir.
- AXIS bu klasördeki modülleri **kendiliğinden içe aktarmaz**. Bir uzantıyı devreye almak ayrı,
  insan onaylı bir değişikliktir.
- Docker yalnızca testi yalıtır; buraya yazılan kod, içe aktarıldığında ana makinede çalışır.
- Kapatma anahtarı: `AXIS_AUTO_APPLY=0`. Ayrıntılar: depo kökündeki `AGENTS.md`.

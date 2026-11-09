# VECTOR Brain V6 — Eğitilmiş Sinir Ağı Laboratuvarı

V5 üzerine eklenenler:

- Gerçek PyTorch XOR ağı (2→8→1), 650 Adam adımıyla eğitim.
- `GET /api/neural?a=1&b=0`: seçilen girişe göre gerçek ağırlık, nöron aktivasyonu, bağlantı sinyali, model tahmini, dört örneklik doğrulama tablosu.
- 3D arayüzde XOR A/B seçicileri; giriş değişince grafik güncellenir.
- `test_v6.py` ile XOR doğruluğu, aktivasyon değişimi ve geçersiz giriş testleri.

## Windows 11

Ollama ve Docker Desktop (Linux containers) önceki sürümdeki gibi isteğe bağlı / ilgili özellikler için gereklidir.

```powershell
py -m pip install -r requirements.txt
py -m pip install torch
py server.py
```

Tarayıcı: http://127.0.0.1:8765

Üstte **Eğitilmiş sinir ağı** düğmesine tıkla, XOR A ve B değerlerini değiştir.

Testler:

```powershell
py -m unittest test_v6.py -v
py -m unittest test_server.py test_v5.py -v
```

## Dürüst sınırlar

- Bu küçük model XOR görevini öğrenmiştir; Qwen3 ağırlıklarını veya VECTOR'un dil modeli aktivasyonlarını göstermez.
- Ağdaki bağlantıların 3D konumları görsel düzenlemedir; gerçek biyolojik konum değildir.
- Self-Evolution Docker testleri temel izolasyon ve sözdizimi kontrolü sağlar; kapsamlı davranış/güvenlik doğrulaması değildir.
- Otomatik bağımsız beceri keşfi, çok-adımlı kod ajanı ve çekirdek kodun kendi kendine güvenli güncellenmesi henüz tamamlanmadı.
- Ağ eğitimi ilk görselleştirme isteğinde birkaç saniye sürebilir.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host 'AXIS kurulumu basliyor...' -ForegroundColor Cyan
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher (py) bulunamadi. Python 3.11 veya 3.12 yukleyin: https://www.python.org/downloads/windows/' }
py -3.12 --version 2>$null
if ($LASTEXITCODE -ne 0) { py -3.11 --version 2>$null; if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 veya 3.12 gereklidir.' }; $pyVer='-3.11' } else { $pyVer='-3.12' }
& py $pyVer -m venv 'AXIS\.venv'
$python = Join-Path $PSScriptRoot 'AXIS\.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install -r 'AXIS\requirements.txt'
Write-Host 'PyTorch kuruluyor (CPU varsayilan; NVIDIA icin READMEye bakin)...' -ForegroundColor Yellow
& $python -m pip install torch
Write-Host 'Kurulum tamamlandi. BASLAT_AXIS.bat dosyasini acin.' -ForegroundColor Green
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Warning 'Ollama kurulu degil. https://ollama.com/download adresinden kurun.' } else { Write-Host 'Model indirmek icin: ollama pull qwen3:8b' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Warning 'Docker bulunamadi. Kod sandbox testleri Docker olmadan calismaz.' }
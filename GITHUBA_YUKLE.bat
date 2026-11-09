@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo Git kurulu degil: https://git-scm.com/download/win & pause & exit /b 1)
git init
git branch -M main
git remote remove origin >nul 2>nul
git remote add origin https://github.com/MussoBenitolini82/AXIS.git
git add .
git commit -m "Import AXIS V12 complete source" || echo Commit olusturulamadi veya degisiklik yok.
git fetch origin main
if errorlevel 1 (echo GitHub fetch basarisiz. & pause & exit /b 1)
git merge origin/main --allow-unrelated-histories -m "Merge initial GitHub repository" -X ours
if errorlevel 1 (echo Merge kontrol gerekli. & pause & exit /b 1)
git push -u origin main
if errorlevel 1 (echo Push basarisiz: GitHub kimlik dogrulamasi gerekebilir. & pause & exit /b 1)
echo AXIS GitHub aktarimi tamamlandi.
pause
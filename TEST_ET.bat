@echo off
cd /d "%~dp0AXIS"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12")
if not defined PY (echo Python 3.12 bulunamadi. Once KUR_AXIS.bat calistirin. & pause & exit /b 1)
%PY% -m unittest discover -p "test*.py" -v
pause

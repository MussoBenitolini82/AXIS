@echo off
cd /d "%~dp0AXIS"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12")
if not defined PY (python --version 2>&1 | find "3.12." >nul && set "PY=python")
if not defined PY (echo Python 3.12 bulunamadi. Once KURULUM.bat calistirin. & pause & exit /b 1)
start "" "http://127.0.0.1:8765"
%PY% server.py
pause

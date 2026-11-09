@echo off
cd /d "%~dp0AXIS"
if not exist ".venv\Scripts\python.exe" (echo Once KURULUM.bat calistirin. & pause & exit /b 1)
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" server.py
pause
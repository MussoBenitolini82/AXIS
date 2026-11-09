@echo off
cd /d "%~dp0AXIS"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m unittest discover -p "test*.py" -v
) else (
  python -m unittest discover -p "test*.py" -v
)
pause

@echo off
cd /d "%~dp0VECTOR"
".venv\Scripts\python.exe" -m unittest discover -p "test_*.py" -v
pause
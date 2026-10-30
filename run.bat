@echo off
cd /d "%~dp0"
if "%~1"=="" (
    echo Usage: run.bat script_name.py
    echo Example: run.bat test_auto.py
    pause
    exit /b
)
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    pause
    exit /b 1
)
.venv\Scripts\python.exe %*
pause
@echo off
cd /d "%~dp0"

echo ================================================
echo   MONSTER AI - Starting Server
echo ================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run setup.
    pause
    exit /b 1
)

echo [INFO] Starting server on http://127.0.0.1:8000
start "MONSTER AI Server" cmd /k ".venv\Scripts\python.exe server.py"

timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8000"

exit
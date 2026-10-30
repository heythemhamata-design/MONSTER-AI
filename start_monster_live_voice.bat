@echo off
cd /d "%~dp0"

echo ================================================
echo   MONSTER AI - LIVE VOICE GATEWAY
echo ================================================

if not exist ".venv-live\Scripts\python.exe" (
    echo [ERROR] Live voice environment not found. Please run setup.
    pause
    exit /b 1
)

echo [INFO] Starting MONSTER Live Voice on http://127.0.0.1:8020
start "MONSTER Live Voice" cmd /k ".venv-live\Scripts\python.exe monster_live_voice_server.py"

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8020/health"
exit
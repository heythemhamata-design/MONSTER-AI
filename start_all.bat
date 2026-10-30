@echo off
cd /d "%~dp0"

echo ================================================
echo   MONSTER AI - START ALL
echo ================================================
echo Current folder: %CD%
echo.

:: ---------- 1) OmniRoute ----------
echo [1/3] Starting OmniRoute...
start "OmniRoute" cmd /k "omniroute"
timeout /t 4 /nobreak >nul

:: ---------- 2) MONSTER AI Server ----------
echo.
echo [2/3] Starting MONSTER AI Server...
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Please run setup.
    pause
    exit /b 1
)
start "MONSTER AI Server" cmd /k ".venv\Scripts\python.exe server.py"
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8000"

:: ---------- 3) MONSTER Live Voice ----------
echo.
echo [3/3] Starting MONSTER Live Voice...
if not exist ".venv-live\Scripts\python.exe" (
    echo [ERROR] .venv-live not found. Please run setup.
    pause
    exit /b 1
)
start "MONSTER Live Voice" cmd /k ".venv-live\Scripts\python.exe monster_live_voice_server.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8020/health"

echo.
echo ================================================
echo   DONE. 3 windows should be open now.
echo ================================================
exit
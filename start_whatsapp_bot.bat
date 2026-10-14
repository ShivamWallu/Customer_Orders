@echo off
title Khandelia Mashal OMS - WhatsApp Automation Bot
color 0A
echo ============================================================
echo   KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
echo   WhatsApp Automation Bot (+91 7814749816)
echo ============================================================
echo.
cd /d "%~dp0"

echo [1/3] Cleaning up any previous orphaned bot sessions...
powershell -Command "Get-CimInstance Win32_Process -Filter \"Name like 'chrome%'\" | Where-Object {$_.CommandLine -like '*whatsapp_chrome_profile*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [2/3] Checking Python Virtual Environment...
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Running with global python...
    echo [3/3] Launching WhatsApp Bot Engine...
    python whatsapp_bot.py
) else (
    echo [3/3] Launching WhatsApp Bot Engine...
    echo.
    echo NOTE: WhatsApp will open and monitor for new orders in real-time.
    echo Keep this window open in background.
    echo.
    venv\Scripts\python.exe whatsapp_bot.py
)
pause

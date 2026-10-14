@echo off
title Khandelia Mashal OMS - Master Launcher
color 0B
echo ============================================================
echo   KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
echo   Master Launcher: OMS Server + WhatsApp Automation
echo ============================================================
echo.
cd /d "%~dp0"

echo [1/2] Starting OMS FastAPI Server on port 8000...
start "Mashal OMS Server (Port 8000)" cmd /k "venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] Starting WhatsApp Automation Bot for +91 7814749816...
start "WhatsApp Automation Bot (+91 7814749816)" cmd /k "venv\Scripts\python.exe whatsapp_bot.py"

echo.
echo ============================================================
echo   SYSTEM ONLINE!
echo   - Order Slip URL:     http://127.0.0.1:8000/
echo   - Sales Table Admin:  http://127.0.0.1:8000/sale_table_data
echo   - WhatsApp Target:    +91 7814749816
echo ============================================================
echo.
pause

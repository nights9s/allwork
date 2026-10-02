@echo off
chcp 65001 >nul
title Office AI Server
cd /d "%~dp0"
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" ^| findstr /c:"192.168."') do set IP=%%a
set IP=%IP: =%
echo ================================================
echo   Office AI Server
echo   เครื่องนี้:         http://localhost:8000
echo   เครื่องอื่นใน LAN:  http://%IP%:8000
echo   ปิดหน้าต่างนี้ = ปิด server
echo ================================================
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause

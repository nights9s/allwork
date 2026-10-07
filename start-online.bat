@echo off
rem Keep this file ASCII only - Thai text breaks how cmd.exe reads batch files
title Office AI - Online (ngrok)
cd /d "%~dp0"

rem ===== Free domain from dashboard.ngrok.com -> Domains =====
set NGROK_DOMAIN=omnivore-rehydrate-appraiser.ngrok-free.dev

rem Use ngrok from PATH, or the winget install folder if PATH is not updated yet
set NGROK=ngrok
where ngrok >nul 2>nul || set NGROK="%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"

rem Start the server in its own window, then open the ngrok tunnel in this one
start "Office AI Server" cmd /k python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
echo ================================================
echo   Office AI - Online
echo   Remote link:  https://%NGROK_DOMAIN%
echo   Close this window = remote link off (office LAN still works)
echo ================================================
%NGROK% http --url=%NGROK_DOMAIN% 8000
pause

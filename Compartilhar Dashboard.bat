@echo off
cd /d "%~dp0"
title Dashboard O^&M - Compartilhar (Grid Co.)
echo ===============================================
echo    Dashboard O^&M  -  COMPARTILHAR (link publico)
echo ===============================================
echo.
echo [1/2] Subindo o servidor local (porta 5050)...
start "Dashboard Server" cmd /c "python app.py"
timeout /t 7 >nul
echo.
echo [2/2] Abrindo o tunel Cloudflare e salvando o link em tunnel_url.txt...
echo.
echo   *** O link aparece abaixo. A senha e a DASH_PASSWORD do .env. ***
echo   *** Para PARAR: feche esta janela E a janela "Dashboard Server". ***
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0subir_tunel.ps1"
echo.
echo (Tunel encerrado.)
pause

@echo off
cd /d "%~dp0"
title Dashboard O&M - Compartilhar (Grid Co.)
echo ===============================================
echo    Dashboard O^&M  -  COMPARTILHAR (link publico)
echo ===============================================
echo.
echo [1/2] Subindo o servidor local (porta 5050)...
start "Dashboard Server" cmd /c "python app.py"
timeout /t 7 >nul
echo.
echo [2/2] Abrindo o tunel Cloudflare...
echo.
echo   *** Compartilhe com a equipe o link https://....trycloudflare.com
echo       que aparecer abaixo (a senha e a DASH_PASSWORD do .env). ***
echo.
echo   *** Para PARAR: feche esta janela E a janela "Dashboard Server". ***
echo.
cloudflared tunnel --url http://localhost:5050
echo.
echo (Tunel encerrado.)
pause

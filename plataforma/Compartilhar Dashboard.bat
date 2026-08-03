@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Dashboard O^&M - Compartilhar (Grid Co.)
echo ===============================================
echo    Dashboard O^&M  -  COMPARTILHAR (link publico)
echo ===============================================
echo.
echo   Garantindo o servidor (porta 5050) e subindo o tunel...
echo   O link aparece abaixo, vai pra area de transferencia e pro seu WhatsApp.
echo   A senha e a DASH_PASSWORD do .env.
echo.
echo   Para PARAR o link: feche esta janela (o servidor continua no ar).
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0subir_tunel.ps1"
echo.
echo (Tunel encerrado.)
pause

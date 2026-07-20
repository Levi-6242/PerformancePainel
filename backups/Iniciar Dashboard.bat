@echo off
cd /d "%~dp0"
title Dashboard O^&M - Grid Co.
echo ===============================================
echo    Dashboard O^&M  -  Grid Co.
echo ===============================================
echo.
echo [1/3] Checando dependencias do Python...
echo       (so demora na primeira vez)
python -m pip install -q -r requirements.txt
echo.
echo [2/3] Abrindo o navegador em http://localhost:5050 ...
start "" /b cmd /c "timeout /t 6 >nul & start http://localhost:5050"
echo.
echo [3/3] Servidor iniciando...
echo.
echo   *** Para PARAR o servidor, feche esta janela. ***
echo.
python app.py
echo.
echo (Servidor encerrado.)
pause

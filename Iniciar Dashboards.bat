@echo off
rem Sobe o dashboard Thopen como processo persistente (sem janela).
rem Thopen -> http://localhost:5080
rem (O painel de PR/Historico agora vive na Plataforma de Performance: Painel > Historico > PR.)
cd /d "%~dp0"

set "PY=C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"

rem Encerra instancia antiga na porta (evita conflito) e sobe de novo
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5080 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

start "" "%PY%" dashboard_thopen.py

echo.
echo  Dashboard iniciado:
echo    Thopen  : http://localhost:5080
echo.
echo  (Pode fechar esta janela.)
timeout /t 4 >nul

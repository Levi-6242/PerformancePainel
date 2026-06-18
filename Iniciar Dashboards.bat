@echo off
rem Sobe os dashboards de Performance como processos persistentes (sem janela).
rem Geracao -> http://localhost:5070   |   Thopen -> http://localhost:5080
cd /d "%~dp0"

set "PY=C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"

rem Encerra instancias antigas nas portas (evita conflito) e sobe de novo
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5070 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5080 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

start "" "%PY%" dashboard_geracao.py
start "" "%PY%" dashboard_thopen.py

echo.
echo  Dashboards iniciados:
echo    Geracao : http://localhost:5070
echo    Thopen  : http://localhost:5080
echo.
echo  (Pode fechar esta janela.)
timeout /t 4 >nul

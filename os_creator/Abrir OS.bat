@echo off
REM Abre o app "Criar OS - Fracttal". Deixe este .bat dentro da pasta os_creator.
cd /d "%~dp0"
"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe" main.py
if errorlevel 1 pause

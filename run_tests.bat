@echo off
REM Roda a suite de testes (Fase 1: funcoes puras de app.py).
REM Uso:  run_tests.bat            -> roda tudo
REM       run_tests.bat -v         -> verboso
REM       run_tests.bat tests\test_strings.py
cd /d "%~dp0"
python -m pytest %*

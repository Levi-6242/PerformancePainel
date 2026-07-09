@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Rodar Ronda de Trackers AGORA (Grid Co.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rodar_ronda.ps1"

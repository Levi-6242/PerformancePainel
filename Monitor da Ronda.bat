@echo off
rem Monitor da Ronda de Trackers - abre em janela propria (estilo aplicativo)
set URL=http://localhost:5050/ronda/monitor
where msedge >/dev/null 2>/dev/null && (start msedge --app=%URL% & exit /b)
if exist "C:\Program Files (x86)\Microsoftdge\Application\msedge.exe" (start "" "C:\Program Files (x86)\Microsoftdge\Application\msedge.exe" --app=%URL% & exit /b)
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=%URL% & exit /b)
start %URL%

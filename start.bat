@echo off
REM Thin wrapper around setup\start.py for Windows.
REM LAN-Zugriff: start.bat --host 0.0.0.0
REM Auf anderen Geraeten: http://<LAN-IP dieses Rechners>:8000 oeffnen.
REM Bei --backend-port PORT stattdessen diesen Port verwenden (nicht --port).
REM Alle Geraete muessen im selben LAN sein; ggf. den Backend-Port in der
REM Firewall freigeben. Der Frontend-Port bleibt intern (Backend-Proxy).
REM Ohne --host ist die App nur lokal erreichbar. Keine Authentifizierung:
REM Nur in vertrauenswuerdigen Netzen freigeben; erreichbar sind auch Decks,
REM Uploads und Spiele. Details: docs/Reference/OPERATIONS.md
setlocal

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    set "PYTHON=py"
)

"%PYTHON%" "%~dp0setup\start.py" %*

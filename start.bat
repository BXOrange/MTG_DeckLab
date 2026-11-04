@echo off
REM Thin wrapper around setup\start.py for Windows.
REM Betriebsarten (Details: docs\Reference\SERVER_GUIDE.md):
REM   start.bat                  = --lan (Standard): Konten per Einladung, nur erlaubte Netze
REM   start.bat --localdev       nur lokal, Standardnutzer "local" ohne Login
REM   start.bat --lan [--allow-network 192.168.179.0/24]
REM                              LAN: Konten per Einladung, nur erlaubte Netze
REM   start.bat --online --tls-cert C.pem --tls-key K.pem  (oder --behind-tls-proxy)
REM                              Internet: nur HTTPS
REM Erste Einladung anlegen: backend\scripts\manage_accounts.py invite
REM Auf anderen Geraeten: http://<LAN-IP dieses Rechners>:8000 oeffnen
REM (--backend-port PORT aendert diesen Port; Firewall ggf. freigeben).
REM accounts.db ist verschluesselt; Schluessel/Backups/Umstellung: docs\Reference\SERVER_GUIDE.md
REM Details: docs\Reference\OPERATIONS.md
setlocal

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    set "PYTHON=py"
)

"%PYTHON%" "%~dp0setup\start.py" %*

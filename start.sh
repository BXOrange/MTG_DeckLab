#!/usr/bin/env bash
# Thin wrapper around setup/start.py for macOS/Linux shells.
# Betriebsarten (Details: docs/Reference/SERVER_GUIDE.md):
#   ./start.sh                  = --lan (Standard): Konten per Einladung, nur erlaubte Netze
#   ./start.sh --localdev       nur lokal, Standardnutzer "local" ohne Login
#   ./start.sh --lan [--allow-network 192.168.179.0/24]
#                               LAN: Konten per Einladung, nur erlaubte Netze
#   ./start.sh --online --tls-cert C.pem --tls-key K.pem   (oder --behind-tls-proxy)
#                               Internet: nur HTTPS
# Erste Einladung anlegen: backend/scripts/manage_accounts.py invite
# Auf anderen Geraeten: http://<LAN-IP dieses Rechners>:8000 oeffnen
# (--backend-port PORT aendert diesen Port; Firewall ggf. freigeben).
# accounts.db ist verschlüsselt; Schlüssel/Backups/Umstellung: docs/Reference/SERVER_GUIDE.md
# Details: docs/Reference/OPERATIONS.md
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    PYTHON=python
fi

exec "${PYTHON}" "${DIR}/setup/start.py" "$@"

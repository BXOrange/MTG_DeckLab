#!/usr/bin/env bash
# Thin wrapper around setup/start.py for macOS/Linux shells.
# LAN-Zugriff: ./start.sh --host 0.0.0.0
# Auf anderen Geraeten: http://<LAN-IP dieses Rechners>:8000 oeffnen.
# Bei --backend-port PORT stattdessen diesen Port verwenden (nicht --port).
# Alle Geraete muessen im selben LAN sein; ggf. den Backend-Port in der
# Firewall freigeben. Der Frontend-Port bleibt intern (Backend-Proxy).
# Ohne --host ist die App nur lokal erreichbar. Keine Authentifizierung:
# Nur in vertrauenswuerdigen Netzen freigeben; erreichbar sind auch Decks,
# Uploads und Spiele. Details: docs/Reference/OPERATIONS.md
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    PYTHON=python
fi

exec "${PYTHON}" "${DIR}/setup/start.py" "$@"

#!/usr/bin/env bash
# Thin wrapper around setup/install.py for macOS/Linux shells.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    PYTHON=python
fi

exec "${PYTHON}" "${DIR}/setup/install.py" "$@"

#!/usr/bin/env bash
# Development-only setup: project-local Node/ESLint plus Python dev tools.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    PYTHON=python
fi

exec "${PYTHON}" "${DIR}/setup/install_dev.py" "$@"

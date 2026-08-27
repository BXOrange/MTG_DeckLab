#!/usr/bin/env python3
"""Regenerate `parser/oracle/PARSER_VERSION.lock` from the current source tree.

Run this after bumping `gate.PARSER_VERSION`, or after any front-end edit
that's confirmed *not* to change parse behavior (e.g. a comment/docstring
change). `tests/test_parser_version_lock.py` fails otherwise — it pins the
front-end source hash for the current `PARSER_VERSION` and catches the
"parser files changed but PARSER_VERSION wasn't bumped" failure mode
`docs/implementation-state/PARSER_LONG_TAIL.md` warns about by hand today.

Usage (from backend/, venv active):
  python scripts/update_parser_version_lock.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer.parser.oracle.gate import PARSER_VERSION, parser_source_hash  # noqa: E402

LOCK_PATH = Path(__file__).resolve().parent.parent / "mtg_analyzer" / "parser" / "oracle" / "PARSER_VERSION.lock"


def main() -> None:
    lock = {"parser_version": PARSER_VERSION, "source_hash": parser_source_hash()}
    LOCK_PATH.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {LOCK_PATH} for PARSER_VERSION={PARSER_VERSION}")


if __name__ == "__main__":
    main()

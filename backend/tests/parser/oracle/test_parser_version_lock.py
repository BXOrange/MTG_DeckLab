"""Ensure parser source and its version lock remain synchronized."""

import json
from pathlib import Path

from mtg_analyzer.parser.oracle.gate import PARSER_VERSION, parser_source_hash

_LOCK_PATH = Path(__file__).resolve().parents[3] / "mtg_analyzer" / "parser" / "oracle" / "PARSER_VERSION.lock"


def test_lock_file_matches_current_parser_version_and_source():
    lock = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))

    assert lock["parser_version"] == PARSER_VERSION, (
        f"PARSER_VERSION is {PARSER_VERSION!r} but PARSER_VERSION.lock still "
        f"pins {lock['parser_version']!r}. Run "
        "`python scripts/update_parser_version_lock.py` to regenerate it."
    )
    assert lock["source_hash"] == parser_source_hash(), (
        "parser/oracle/**/*.py changed since PARSER_VERSION was last locked, "
        "but PARSER_VERSION was not bumped. If this is a real parsing-behavior "
        "change, bump PARSER_VERSION in gate.py. If it's confirmed "
        "behavior-neutral (e.g. a comment/docstring edit), re-run "
        "`python scripts/update_parser_version_lock.py` to update the pin."
    )

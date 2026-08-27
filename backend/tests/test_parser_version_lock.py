"""Guard: a front-end edit must not silently outrun `PARSER_VERSION`.

Reference: docs/implementation-state/PARSER_LONG_TAIL.md, which had to warn
readers by hand that "measuring twice within one batch... silently reuses
the first run's rows" if `PARSER_VERSION` isn't bumped alongside a real
parser change — coverage-ledger rows are keyed on
`(PARSER_VERSION, content)` (`services/coverage_db.content_hash`), so a
handler edit that isn't matched by a version bump is invisible to
`scripts/coverage_report.py`'s ledger reuse. This test makes that
structurally detectable instead of a discipline someone has to remember.

If this fails after a legitimate change: bump `PARSER_VERSION` in
`parser/oracle/gate.py` (a real behavior change), or just re-run
`scripts/update_parser_version_lock.py` (a confirmed behavior-neutral edit,
e.g. a comment) — either way, regenerate the lock file.
"""

import json
from pathlib import Path

from mtg_analyzer.parser.oracle.gate import PARSER_VERSION, parser_source_hash

_LOCK_PATH = Path(__file__).resolve().parent.parent / "mtg_analyzer" / "parser" / "oracle" / "PARSER_VERSION.lock"


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

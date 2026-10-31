"""BUG-13: printed colours of every real card face match Scryfall's face colours.

Rebuilds `printed_colors` for each face in the raw Scryfall store (opened
read-only) and compares with Scryfall's own ``colors``, so the generated
`card_color_table.py` can't drift from the card pool (regenerate with
`scripts/generate_card_color_table.py`). Split / adventure / prepare halves are
skipped (each half is coloured by its own cost; Scryfall's per-face colours there
describe the whole card), as are tokens/emblems/art cards and ambiguous face names.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from mtg_analyzer.models.cards.card_colors import printed_colors

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import generate_card_color_table as gen  # noqa: E402

pytestmark = pytest.mark.full_cache

#: Face names shared by different cards with different colours (Un-set gags); resolved by cost instead.
AMBIGUOUS_NAMES = frozenset({"Fire", "Start"})


class _Face:
    def __init__(self, view):
        self.name = view.name
        self.mana_cost_string = view.mana_cost_string
        self.oracle_text = view.oracle_text
        self.keywords = view.keywords
        self.type_line = ""
        self.color_identity = set()


@pytest.mark.skipif(not gen.RAW_DB.exists(), reason="raw Scryfall store not present")
def test_printed_colors_match_scryfall_face_colors():
    con = sqlite3.connect(f"file:{gen.RAW_DB}?mode=ro", uri=True)
    mismatches = []
    for data, face, multi in gen.iter_faces(con):
        truth = gen.face_truth(data, face, multi)
        view = gen.FaceView(data, face, multi)
        if truth is None or view.name in AMBIGUOUS_NAMES:
            continue
        if printed_colors(_Face(view)) != truth:
            mismatches.append((view.name, sorted(printed_colors(_Face(view))), sorted(truth)))
    assert not mismatches, mismatches[:20]


@pytest.mark.skipif(not gen.RAW_DB.exists(), reason="raw Scryfall store not present")
def test_checked_in_table_is_current():
    assert gen.TABLE_PATH.read_text(encoding="utf-8") == gen.render(gen.build_table())

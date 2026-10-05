"""Secrets of Strixhaven — playability batch, wave 14.

Wave 14 (PARSER_VERSION 289 -> 290): "**whenever you cast a <colour>
spell, …**" — `segmenter._CAST_SPELL_TRIGGER_RE`'s dispatch gained a colour
branch (`_CAST_SPELL_COLOR_WORDS`) alongside the existing main-type and
creature-subtype branches, emitting `effect_binder`'s already-shipped
``cast_of_color`` trigger key (the Runaway Steam-Kin predicate). Unblocks
Balefire Liege (Lorehold deck).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _seg(text):
    return segment_line(text, allow_spell_effect=False, provenance=ParserProvenance())


@pytest.mark.parametrize("clause,color", [
    ("whenever you cast a red spell, you gain 3 life", "R"),
    ("whenever you cast a white spell, you gain 3 life", "W"),
    ("whenever you cast a blue spell, you draw a card", "U"),
    ("whenever you cast a black spell, you draw a card", "B"),
    ("whenever you cast a green spell, you gain 3 life", "G"),
])
def test_color_cast_trigger_claimed(clause, color):
    seg = _seg(clause)
    assert seg.claimed, clause
    assert seg.spec.trigger["event"] == "SPELL_CAST"
    assert seg.spec.trigger["spell_filter"] == {"color": color}


def test_colorless_spell_cast_is_not_folded_into_cast_of_color():
    # `cast_of_color` is a membership check, not an empty-identity one —
    # "colorless" must not fold in. PAR-119 gives it its own filter key
    # (`spell_filter={"colorless": True}`, an empty-colour-set test).
    seg = _seg("whenever you cast a colorless spell, you draw a card")
    assert seg.claimed
    assert "cast_of_color" not in seg.spec.trigger
    assert seg.spec.trigger["spell_filter"] == {"colorless": True}


def test_main_type_cast_trigger_unchanged():
    seg = _seg("whenever you cast a creature spell, you gain 1 life")
    assert seg.claimed
    assert seg.spec.trigger.get("spell_filter") == {"card_type": "creature"}


def test_balefire_liege_modeled():
    r = parse_oracle(_db().get_card("Balefire Liege"))
    assert r.coverage != UNMODELED, r.unclaimed
    trigs = [s.trigger for s in r.specs if s.trigger]
    colors = {(t.get("spell_filter") or {}).get("color") for t in trigs if t.get("event") == "SPELL_CAST"}
    assert colors == {"R", "W"}


def test_emberstrike_duo_two_color_triggers():
    r = parse_oracle(_db().get_card("Emberstrike Duo"))
    assert r.coverage != UNMODELED, r.unclaimed
    colors = sorted(s.trigger["spell_filter"]["color"] for s in r.specs if s.trigger)
    assert colors == ["B", "R"]

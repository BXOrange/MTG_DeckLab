"""PAR-284: "for each color | card type | different mana value among <objects>" (RULE 105.2, 205.2a, 202.3).

The distinct-value count (`continuous._DISTINCT_SET_KEYS` / `_DISTINCT_KEYS`) already measured "the number of colors
among ..."; the "for each" spelling is singular and "different mana values" had no count-phrase reading.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _cast, _engine


def _amount(oracle):
    specs = parse_effect_body(oracle)
    assert specs is not None and [s.type for s in specs] == ["bind"], specs
    return specs[0].params["amount"]["selector"]


@pytest.mark.parametrize("oracle, distinct, zone", [
    ("draw a card for each color among permanents you control.", "color", "battlefield"),
    ("draw a card for each card type among cards in your graveyard.", "card_type", "graveyard"),
    ("draw a card for each different mana value among nonland permanents you control.", "mana_value", "battlefield"),
    ("draw x cards, where x is the number of different mana values among cards in your graveyard.", "mana_value", "graveyard"),
])
def test_distinct_among_reads_as_a_count_selector(oracle, distinct, zone):
    selector = _amount(oracle)
    assert selector["distinct"] == distinct and selector["zone"] == zone


@pytest.mark.parametrize("oracle", [
    "draw a card for each name among permanents you control.",
])
def test_unlisted_distinct_values_stay_unclaimed(oracle):
    assert parse_effect_body(oracle) is None


def test_real_cards_are_modeled():
    for name, type_line, oracle in [
        ("Lunar Insight", "Sorcery", "Draw a card for each different mana value among nonland permanents you control."),
        ("Karn, Gilded Guardian", "Legendary Artifact Creature — Construct",
         "When this creature enters, draw a card for each color among other artifacts you control."),
    ]:
        result = parse_oracle(_card(name, type_line, oracle, is_sorcery=type_line == "Sorcery"))
        assert result.modeled, (name, result.unclaimed)


def _permanent(eng, name, mv, **kw):
    obj = GameObject(_card(name, "Creature — Bear", mv=mv, is_creature=True, power=1, toughness=1, **kw),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    eng.state.battlefield.append(obj)


def test_lunar_insight_draws_one_per_different_mana_value():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(6):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    for name, mv in (("A", 2), ("B", 2), ("C", 4)):  # two different mana values among three permanents
        _permanent(eng, name, mv)
    _cast(eng, "Draw a card for each different mana value among nonland permanents you control.")
    assert len(p1.hand) == 2

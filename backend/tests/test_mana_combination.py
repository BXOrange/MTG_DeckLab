"""Tests for RULE 605.1a "add N mana in any combination of colours" —
a genuinely different shape from "any one colour": the payer *splits* the
resolved total across colours instead of picking a single colour repeated
N times. Covers the parser (`ManaAbility.any_combination`,
`_parse_combination_selector`, the new "literal"/"greatest_power_control"
`_resolve_amount` kinds), `validate_color_split`, and the engine payment
path (`GameEngine.tap_for_mana`'s ``color_split`` parameter).

Verified against the real cache cards: Flamebraider/Gwenna, Eyes of
Gaea/Smokebraider (fixed "two") and Selvala, Heart of the Wilds (variable
"X", the greatest power among creatures you control).

Reference: backend/ToDo_Backend.md, docs/implementation-state/Done_Backend.md.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import (
    mana_abilities_for,
    parse_mana_abilities,
    validate_color_split,
)


def _dork(name, oracle, **kw):
    return Card(
        id=name, name=name, type_line="Creature — Elemental", is_creature=True,
        oracle_text=oracle, **kw,
    )


# ---------------------------------------------------------------------------
# Parsing (game/mana_abilities.py)
# ---------------------------------------------------------------------------


def test_fixed_amount_is_tagged_any_combination():
    card = _dork(
        "Flamebraider",
        "{T}: Add two mana in any combination of colors. Spend this mana only "
        "to cast Elemental spells or activate abilities of Elemental sources.",
    )
    [ability] = parse_mana_abilities(card)
    assert ability.any_combination is True
    assert ability.options == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]
    assert ability.amount_selector == {"kind": "literal", "n": 2}
    assert ability.restriction == {
        "kind": "type_spell", "types": ["elemental"], "allow_ability": True,
    }


def test_resolved_options_scale_the_fixed_total_per_color():
    card = _dork("Gwenna Stub", "{T}: Add two mana in any combination of colors.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    [ability] = mana_abilities_for(obj)
    assert ability.any_combination is True
    assert ability.options == [{"W": 2}, {"U": 2}, {"B": 2}, {"R": 2}, {"G": 2}]


def test_variable_amount_selector_is_greatest_power_control():
    card = _dork(
        "Selvala Stub",
        "{G}, {T}: Add X mana in any combination of colors, "
        "where X is the greatest power among creatures you control.",
    )
    [ability] = parse_mana_abilities(card)
    assert ability.any_combination is True
    assert ability.amount_selector == {"kind": "greatest_power_control"}
    assert ability.cost.mana.symbols  # {G} is part of the cost, not the production


def test_greatest_power_resolves_against_the_battlefield():
    card = _dork(
        "Selvala Stub",
        "{G}, {T}: Add X mana in any combination of colors, "
        "where X is the greatest power among creatures you control.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    big = GameObject(
        Card(id="Big", name="Big", type_line="Creature — Giant", is_creature=True, power=7, toughness=7),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    opponents_bigger = GameObject(
        Card(id="Bigger", name="Bigger", type_line="Creature — Giant", is_creature=True, power=99, toughness=99),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    state = GameState(players=[Player(id="p1", name="P1"), Player(id="p2", name="P2")])
    state.battlefield.extend([obj, big, opponents_bigger])
    [ability] = mana_abilities_for(obj, state=state)
    assert ability.options == [{"W": 7}, {"U": 7}, {"B": 7}, {"R": 7}, {"G": 7}]


def test_greatest_power_with_no_creatures_is_zero():
    card = _dork(
        "Selvala Stub",
        "{G}, {T}: Add X mana in any combination of colors, "
        "where X is the greatest power among creatures you control.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state = GameState(players=[Player(id="p1", name="P1")])
    state.battlefield.append(obj)
    [ability] = mana_abilities_for(obj, state=state)
    assert ability.options == [{"W": 0}, {"U": 0}, {"B": 0}, {"R": 0}, {"G": 0}]


def test_unrecognised_x_subject_leaves_no_mana_ability():
    # Fail-soft: an "X mana in any combination of colors, where X is ..."
    # naming a subject outside the recognised vocabulary parses to no mana
    # ability at all, same as before this shape existed (never a
    # regression — it produced nothing before either).
    card = _dork(
        "Hypothetical",
        "{T}: Add X mana in any combination of colors, "
        "where X is the number of lands you control.",
    )
    assert parse_mana_abilities(card) == []


# ---------------------------------------------------------------------------
# validate_color_split
# ---------------------------------------------------------------------------


def test_validate_color_split_accepts_a_matching_total():
    assert validate_color_split({"W": 1, "G": 1}, 2) == {"W": 1, "G": 1}


def test_validate_color_split_drops_zero_entries():
    assert validate_color_split({"W": 2, "U": 0}, 2) == {"W": 2}


def test_validate_color_split_rejects_wrong_total():
    with pytest.raises(ValueError):
        validate_color_split({"W": 1}, 2)


def test_validate_color_split_rejects_unknown_color():
    with pytest.raises(ValueError):
        validate_color_split({"X": 2}, 2)


def test_validate_color_split_rejects_negative_amount():
    with pytest.raises(ValueError):
        validate_color_split({"W": -1, "G": 3}, 2)


# ---------------------------------------------------------------------------
# End-to-end through the engine (GameEngine.tap_for_mana)
# ---------------------------------------------------------------------------


def _make_engine(cards, hand=0):
    return GameEngine.new_game([("p1", "Alice", list(cards))], starting_life=20, starting_hand=hand)


def test_tap_for_mana_defaults_to_one_color_without_a_split():
    card = _dork("Gwenna Stub", "{T}: Add two mana in any combination of colors.")
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    produced = eng.tap_for_mana(p1, obj)
    assert produced == {"W": 2}  # option_index 0's single-colour default
    assert p1.mana_pool.total() == 2


def test_tap_for_mana_honours_an_explicit_color_split():
    card = _dork("Gwenna Stub", "{T}: Add two mana in any combination of colors.")
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    produced = eng.tap_for_mana(p1, obj, color_split={"W": 1, "G": 1})
    assert produced == {"W": 1, "G": 1}
    assert p1.mana_pool.total() == 2
    assert p1.mana_pool.pool["W"] == 1
    assert p1.mana_pool.pool["G"] == 1


def test_tap_for_mana_rejects_a_split_with_the_wrong_total():
    card = _dork("Gwenna Stub", "{T}: Add two mana in any combination of colors.")
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, obj, color_split={"W": 1})


def test_color_split_is_ignored_for_a_non_combination_ability():
    # A dual land's "W or U" isn't `any_combination` — an incidental
    # `color_split` is simply unused, `option_index` still decides.
    land = Card(id="Tundra", name="Tundra", type_line="Land — Plains Island", is_land=True, oracle_text="{T}: Add {W} or {U}.")
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = GameObject(land, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    produced = eng.tap_for_mana(p1, obj, option_index=1, color_split={"W": 1, "U": 5})
    assert produced == {"U": 1}


def test_combination_mana_carries_its_restriction_when_present():
    card = _dork(
        "Smokebraider",
        "{T}: Add two mana in any combination of colors. Spend this mana only "
        "to cast Elemental spells or activate abilities of Elementals.",
    )
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    eng.tap_for_mana(p1, obj, color_split={"R": 1, "G": 1})
    assert p1.mana_pool.total() == 2
    assert p1.mana_pool.pool["R"] == 0  # tagged into a restricted lot, not the flat pool
    assert p1.mana_pool.pool["G"] == 0


def test_legal_actions_surfaces_the_combination_flag_and_total():
    card = _dork("Gwenna Stub", "{T}: Add two mana in any combination of colors.")
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    [action] = [a for a in eng.legal_actions(p1) if a.get("type") == "tap_for_mana"]
    assert action["any_combination"] is True
    assert action["combination_total"] == 2

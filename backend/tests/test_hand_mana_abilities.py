"""Tests for RULE 605.1a "Exile this card from your hand: Add …" mana
abilities (Elvish Spirit Guide, Simian Spirit Guide) — the hand-zone
counterpart of a permanent's battlefield tap-for-mana ability. Covers the
parser split (`parse_mana_abilities` excludes these lines,
`hand_mana_abilities`/`hand_mana_abilities_for` pick them up instead) and
the engine payment path (`GameEngine.activate_hand_mana_ability`).

Reference: backend/ToDo_Backend.md, docs/implementation-state/Done_Backend.md.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import (
    hand_mana_abilities,
    hand_mana_abilities_for,
    parse_mana_abilities,
)


def _spirit_guide(name="Simian Spirit Guide", color="R", type_line="Creature — Ape Spirit"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        oracle_text=f"Exile this card from your hand: Add {{{color}}}.",
    )


# ---------------------------------------------------------------------------
# Parsing (game/mana_abilities.py)
# ---------------------------------------------------------------------------


def test_hand_exile_line_is_never_a_battlefield_mana_ability():
    card = _spirit_guide()
    assert parse_mana_abilities(card) == []


def test_hand_exile_line_is_a_hand_mana_ability():
    card = _spirit_guide()
    [ability] = hand_mana_abilities(card)
    assert ability.cost.exile_self_from_hand is True
    assert ability.options == [{"R": 1}]


def test_hand_mana_abilities_for_resolves_a_game_object_in_hand():
    card = _spirit_guide(color="G")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    [ability] = hand_mana_abilities_for(obj)
    assert ability.options == [{"G": 1}]


def test_a_card_can_print_both_a_battlefield_and_a_hand_exile_ability():
    # Not a real card — verifies the split stays correct per line even
    # when both shapes appear on the same oracle text.
    card = Card(
        id="Hybrid Stub", name="Hybrid Stub", type_line="Creature — Elf",
        is_creature=True,
        oracle_text="{T}: Add {G}.\nExile this card from your hand: Add {R}.",
    )
    [battlefield_ability] = parse_mana_abilities(card)
    assert battlefield_ability.options == [{"G": 1}]
    [hand_ability] = hand_mana_abilities(card)
    assert hand_ability.options == [{"R": 1}]


def test_non_hand_exile_card_has_no_hand_mana_abilities():
    card = Card(
        id="Llanowar Elves", name="Llanowar Elves", type_line="Creature — Elf Druid",
        is_creature=True, oracle_text="{T}: Add {G}.",
    )
    assert hand_mana_abilities(card) == []


def test_hand_exile_combination_ability_carries_any_combination():
    # A hypothetical card combining the two Batch 7/8 shapes — verifies
    # `any_combination`/`amount_selector` thread through the hand-zone
    # parse path exactly like the battlefield one.
    card = Card(
        id="Hand Combo Stub", name="Hand Combo Stub", type_line="Creature — Elemental",
        is_creature=True,
        oracle_text="Exile this card from your hand: Add two mana in any combination of colors.",
    )
    [ability] = hand_mana_abilities(card)
    assert ability.any_combination is True
    assert ability.amount_selector == {"kind": "literal", "n": 2}


# ---------------------------------------------------------------------------
# End-to-end through the engine (GameEngine.activate_hand_mana_ability)
# ---------------------------------------------------------------------------


def _make_engine(cards, hand=0):
    return GameEngine.new_game([("p1", "Alice", list(cards))], starting_life=20, starting_hand=hand)


def test_activate_hand_mana_ability_exiles_the_card_and_produces_mana():
    guide = _spirit_guide()
    eng = _make_engine([guide], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = p1.hand[0]

    produced = eng.activate_hand_mana_ability(p1, obj)
    assert produced == {"R": 1}
    assert obj not in p1.hand
    assert obj in p1.exile
    assert p1.mana_pool.total() == 1
    assert p1.mana_pool.pool["R"] == 1


def test_activate_hand_mana_ability_rejects_a_source_not_in_hand():
    guide = _spirit_guide()
    other = Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True)
    eng = _make_engine([other, guide], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    on_battlefield = GameObject(other, owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(on_battlefield)

    with pytest.raises(ValueError):
        eng.activate_hand_mana_ability(p1, on_battlefield)


def test_legal_actions_offers_activate_hand_mana():
    guide = _spirit_guide()
    eng = _make_engine([guide], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = p1.hand[0]

    [action] = [a for a in eng.legal_actions(p1) if a.get("type") == "activate_hand_mana"]
    assert action["instance_id"] == obj.instance_id
    assert action["options"] == [{"index": 0, "mana": {"R": 1}, "label": "🔴"}]


def test_color_split_works_through_the_hand_zone_path():
    card = Card(
        id="Hand Combo Stub", name="Hand Combo Stub", type_line="Creature — Elemental",
        is_creature=True,
        oracle_text="Exile this card from your hand: Add two mana in any combination of colors.",
    )
    eng = _make_engine([card], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = p1.hand[0]

    produced = eng.activate_hand_mana_ability(p1, obj, color_split={"W": 1, "G": 1})
    assert produced == {"W": 1, "G": 1}
    assert obj in p1.exile
    assert p1.mana_pool.total() == 2


def test_restriction_is_tagged_on_hand_produced_mana():
    card = Card(
        id="Restricted Guide", name="Restricted Guide", type_line="Creature — Elemental",
        is_creature=True,
        oracle_text=(
            "Exile this card from your hand: Add {R}. "
            "Spend this mana only to cast an Elemental spell."
        ),
    )
    eng = _make_engine([card], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = p1.hand[0]

    eng.activate_hand_mana_ability(p1, obj)
    assert p1.mana_pool.total() == 1
    assert p1.mana_pool.pool["R"] == 0  # tagged into a restricted lot, not the flat pool

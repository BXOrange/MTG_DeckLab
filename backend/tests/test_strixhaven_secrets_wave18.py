"""Secrets of Strixhaven — playability batch, wave 18.

Wave 18 (PARSER_VERSION 293 -> 294): a phase trigger's leading RULE 603.4
intervening-if "if you control no <subtype>[s]" / "if you don't control a
<subtype> [creature] token" (`segmenter._YOU_CONTROL_NO_SUBTYPE_IF_RE`) ->
the trigger's ``active_if`` as `static_conditions`' ``control_count`` with
``max=0`` over the ``creatures_you_control_of_type_<subtype>`` selector.
Unblocks Ophiomancer and Pest Rescuer (Witherbloom deck).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _seg(text):
    return segment_line(text, allow_spell_effect=False, provenance=ParserProvenance())


@pytest.mark.parametrize("clause,sub", [
    ("at the beginning of each upkeep, if you control no snakes, "
     "create a 1/1 black snake creature token with deathtouch", "snake"),
    ("at the beginning of your upkeep, if you don't control a pest creature token, "
     "create a 1/1 black and green pest creature token", "pest"),
])
def test_control_no_subtype_intervening_if_claimed(clause, sub):
    seg = _seg(clause)
    assert seg.claimed, clause
    aif = seg.spec.trigger["active_if"]
    assert aif == {"kind": "control_count",
                   "selector": f"creatures_you_control_of_type_{sub}", "max": 0}
    assert [e.type for e in seg.spec.effects] == ["create_token"]


def test_unwhitelisted_subtype_falls_through_unchanged():
    # "no Food" must keep routing to its own (pre-existing) handler, not be
    # swallowed by this one.
    r = parse_oracle(_db().get_card("Butterbur, Bree Innkeeper"))
    assert r.coverage != UNMODELED, r.unclaimed


@pytest.mark.parametrize("name", ["Ophiomancer", "Pest Rescuer"])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_control_count_max_zero_gates_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    cond = {"kind": "control_count",
            "selector": "creatures_you_control_of_type_snake", "max": 0}
    assert condition_holds(cond, eng.state, None, p1.id) is True
    snake = GameObject(card=Card(id="s", name="Snek", type_line="Creature — Snake",
                                 is_creature=True, power=1, toughness=1),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
    snake.controller_id = p1.id
    eng.state.add_to_battlefield(snake)
    assert condition_holds(cond, eng.state, None, p1.id) is False

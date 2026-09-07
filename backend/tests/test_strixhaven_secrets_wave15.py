"""Secrets of Strixhaven — playability batch, wave 15.

Wave 15 (PARSER_VERSION 290 -> 291): "**<subject> gets +x/+x [and gains
<kw>] until end of turn**" — new `handlers._pump_x`, tried ahead of the
digits-only `pump` row, emits the ``"x"`` power/toughness sentinel that
`RulesEngine._substitute_x` already rewrites to `GameObject.x_paid` at
resolution. Symmetric bare form only; a "where X is <board count>" tail
stays fail-closed. Unblocks Tyvar's Stand and Primal Might (Quandrix deck).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules.casting_mixin import CastingResolutionMixin
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("clause,tk,kw", [
    ("target creature gets +x/+x until end of turn", "creature", None),
    ("target creature you control gets +x/+x until end of turn",
     "creature_you_control", None),
    ("target creature you control gets +x/+x and gains hexproof and indestructible until end of turn",
     "creature_you_control", ["hexproof", "indestructible"]),
])
def test_pump_x_claimed(clause, tk, kw):
    specs = match_clause(clause)
    assert [s.type for s in specs] == ["pump"]
    p = specs[0].params
    assert p["power"] == "x" and p["toughness"] == "x"
    assert p["target_kind"] == tk
    assert p.get("keywords") == kw


def test_dynamic_board_count_x_stays_fail_closed():
    # "where X is <board count>" is a different family (amount_from_count_selector).
    assert not match_clause(
        "target creature gets +x/+x until end of turn, where x is the number "
        "of card types among cards in all graveyards"
    )


def test_plain_digit_pump_unchanged():
    specs = match_clause("target creature gets +3/+3 until end of turn")
    assert specs[0].params["power"] == 3


@pytest.mark.parametrize("name", ["Tyvar's Stand", "Untamed Might", "Primal Might"])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_pump_x_resolves_to_x_paid_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="s", name="TS", type_line="Instant", is_instant=True),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    src.x_paid = 3
    bear = GameObject(card=Card(id="b", name="Bear", type_line="Creature — Bear",
                                is_creature=True, power=2, toughness=2),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    bear.controller_id = p1.id
    eng.state.add_to_battlefield(bear)
    eff = EffectRegistry.create("pump", {
        "power": "x", "toughness": "x", "target_kind": "creature_you_control"})
    eff.source = src
    CastingResolutionMixin._substitute_x([eff], 3)
    eff.apply(eng.rules.context, targets=[bear])
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 5)

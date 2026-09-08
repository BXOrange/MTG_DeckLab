"""Secrets of Strixhaven — playability batch, wave 9.

Wave 9: "double the number of [+1/+1] counters on <subject>"
(`handlers._DOUBLE_COUNTERS_RE`). The existing `double_counters_on_target`
effect grew a `mode` (self / target / each_you_control / previous_subject)
and an optional `kind` filter.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("clause,expect", [
    ("double the number of +1/+1 counters on ~", {"kind": "+1/+1", "mode": "self"}),
    ("double the number of +1/+1 counters on each creature you control",
     {"kind": "+1/+1", "mode": "each_you_control"}),
    ("double the number of +1/+1 counters on that creature",
     {"kind": "+1/+1", "mode": "previous_subject"}),
    ("double the number of +1/+1 counters on target creature you control",
     {"kind": "+1/+1", "mode": "target", "target_kind": "creature_you_control"}),
])
def test_double_counters_clause_modes(clause, expect):
    specs = match_clause(clause, self_subject=True)
    assert specs == [type(specs[0])("double_counters_on_target", expect)]


@pytest.mark.parametrize("name", [
    "Primordial Hydra", "Kalonian Hydra", "Dragonsguard Elite",
    "Growth Curve", "Bristly Bill, Spine Sower",
])
def test_double_counters_cards_modeled(name):
    c = _db().get_card(name)
    if c is None:
        pytest.skip(f"{name} not cached")
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_self_mode_doubles_only_named_kind():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(Card(id="h", name="H", type_line="Creature — Hydra",
                          is_creature=True, power=1, toughness=1),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    src.counters["+1/+1"] = 4
    src.counters["charge"] = 2
    eff = EffectRegistry.create("double_counters_on_target", {"mode": "self", "kind": "+1/+1"})
    eff.source = src
    eff.apply(eng.rules.context)
    assert src.counters["+1/+1"] == 8
    assert src.counters["charge"] == 2  # untouched — kind filter


def test_each_you_control_mode():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    mine = []
    for i in range(2):
        o = GameObject(Card(id=f"m{i}", name="M", type_line="Creature — Elf",
                            is_creature=True, power=1, toughness=1),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
        o.controller_id = p1.id
        o.counters["+1/+1"] = 2
        eng.state.add_to_battlefield(o)
        mine.append(o)
    theirs = GameObject(Card(id="t", name="T", type_line="Creature — Goblin",
                             is_creature=True, power=1, toughness=1),
                        owner_id=p2.id, zone=Zone.BATTLEFIELD)
    theirs.controller_id = p2.id
    theirs.counters["+1/+1"] = 2
    eng.state.add_to_battlefield(theirs)

    src = GameObject(Card(id="s", name="S", type_line="Creature — Hydra", is_creature=True,
                          power=1, toughness=1), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    eff = EffectRegistry.create("double_counters_on_target", {"mode": "each_you_control", "kind": "+1/+1"})
    eff.source = src
    eff.apply(eng.rules.context)
    assert all(o.counters["+1/+1"] == 4 for o in mine)
    assert theirs.counters["+1/+1"] == 2  # opponent's untouched

"""Secrets of Strixhaven — playability batch, wave 11.

Wave 11: "target creature [you control] has base power and toughness N/N
until end of turn" — `handlers._BASE_PT_UNTIL_EOT_RE` widened from the
~/creatures-you-control subjects to a RULE 115 target. Unblocks Quandrix
Charm's third modal mode.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("clause,tk", [
    ("target creature has base power and toughness 5/5 until end of turn", "creature"),
    ("target creature you control has base power and toughness 5/5 until end of turn",
     "creature_you_control"),
])
def test_base_pt_target_clause(clause, tk):
    specs = match_clause(clause)
    assert specs[0].type == "grant_until"
    assert specs[0].params["target_kind"] == tk
    assert specs[0].params["static"]["type"] == "pt_set"
    assert specs[0].params["static"]["params"]["power"] == 5


def test_self_base_pt_clause_still_untargeted():
    specs = match_clause("~ has base power and toughness 3/3 until end of turn", self_subject=True)
    assert specs[0].params["target_kind"] is None


def test_quandrix_charm_fully_modeled():
    r = parse_oracle(_db().get_card("Quandrix Charm"))
    assert r.coverage != UNMODELED, r.unclaimed
    opt_types = [[e.type for e in opt]
                 for opt in [s for s in r.specs if s.modes][0].modes["options"]]
    assert ["grant_until"] in opt_types
    assert ["counter"] in opt_types


def test_targeted_base_pt_applies_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(Card(id="s", name="S", type_line="Instant", is_instant=True),
                     owner_id=p1.id, zone=Zone.STACK)
    bear = GameObject(Card(id="c", name="C", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    bear.controller_id = p1.id
    eng.state.add_to_battlefield(bear)
    eff = EffectRegistry.create("grant_until", {
        "static": {"type": "pt_set", "params": {"power": 5, "toughness": 5, "affects": "self"}},
        "duration": "end_of_turn", "target_kind": "creature",
    })
    eff.source = src
    eff.apply(eng.rules.context, targets=[bear])
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 5)

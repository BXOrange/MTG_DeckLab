"""Secrets of Strixhaven — playability batch, wave 30 (PAR-60).

Lorehold spirits: graveyard-reanimate-by-dynamic-mana-value + phasing,
hand-authored in `game/ability_catalogue/commander_cards.py`. Engine:
`targeting.legal_targets` gained ``max_mana_value`` sentinels ``source_power``
and ``trigger_damage_amount``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WAVE30 = ["Guardian Scalelord", "Venerable Warsinger", "Drumbellower",
          "Guardian of Faith"]


@pytest.mark.parametrize("name", WAVE30)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature — Spirit",
                              is_creature=True, power=4),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player


def test_source_power_sentinel_caps_graveyard_targets():
    eng, p1 = _eng()
    scale = GameObject(card=Card(id="gs", name="Guardian Scalelord",
                                type_line="Creature — Dragon", is_creature=True,
                                power=3, toughness=3),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
    scale.controller_id = p1.id
    eng.state.add_to_battlefield(scale)
    for mv, name in [(2, "Cheap"), (5, "Pricey")]:
        c = GameObject(card=Card(id=name, name=name,
                                 type_line="Artifact", mana_cost_string="{%d}" % mv),
                       owner_id=p1.id, zone=Zone.GRAVEYARD)
        c.card.converted_mana_cost = mv
        p1.graveyard.append(c)
    spec = _REGISTRY["guardian scalelord"]()[0].effects[0]
    from mtg_analyzer.game.targeting import TargetSpec
    ts = TargetSpec(kind="graveyard_nonland_permanent", max_mana_value="source_power")
    names = {t["name"] for t in legal_targets(eng.state, p1.id, ts, source=scale)}
    assert "Cheap" in names and "Pricey" not in names
    scale.card.power = 6
    scale.reset_derived()
    eng.recompute_continuous_effects()
    names = {t["name"] for t in legal_targets(eng.state, p1.id, ts, source=scale)}
    assert "Pricey" in names


def test_trigger_damage_amount_sentinel():
    eng, p1 = _eng()
    ward = GameObject(card=Card(id="vw", name="Venerable Warsinger",
                               type_line="Creature — Spirit Cleric", is_creature=True,
                               power=3, toughness=3),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    ward.controller_id = p1.id
    eng.state.add_to_battlefield(ward)
    c = GameObject(card=Card(id="C4", name="Four", type_line="Creature — Bear", is_creature=True),
                   owner_id=p1.id, zone=Zone.GRAVEYARD)
    c.card.converted_mana_cost = 4
    p1.graveyard.append(c)
    from mtg_analyzer.game.targeting import TargetSpec
    ts = TargetSpec(kind="graveyard_creature", max_mana_value="trigger_damage_amount")
    got = {t["name"] for t in legal_targets(eng.state, p1.id, ts, source=ward,
                                            trigger_event={"amount": 2})}
    assert "Four" not in got
    got = {t["name"] for t in legal_targets(eng.state, p1.id, ts, source=ward,
                                            trigger_event={"amount": 5})}
    assert "Four" in got

"""Secrets of Strixhaven — playability batch, wave 53 (PAR-60).

Oran-Rief, the Vastwood — new ``entered_this_turn`` key in
``combat.matches_object_filter`` (`GameObject.turn_entered` vs the current
turn); ``AddCountersEffect``'s ``selector`` branch now threads ``state`` into
that call so a mass counter effect can narrow to just-entered creatures.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _cre(eng, cid, name, ci, ctrl):
    obj = GameObject(card=Card(id=cid, name=name, type_line="Creature — X", is_creature=True,
                              power=1, toughness=1, color_identity=ci),
                     owner_id=ctrl, zone=Zone.BATTLEFIELD)
    obj.controller_id = ctrl
    eng.state.add_to_battlefield(obj)
    return obj


def test_oran_rief_registered_and_binds():
    assert is_registered("Oran-Rief, the Vastwood")
    spec = _REGISTRY["oran-rief, the vastwood"]()[0]
    spec.validate()
    eff = spec.effects[0]
    assert eff.type == "add_counters"
    assert eff.params["selector"] == "each_creature"
    assert eff.params["creature_filter"] == {"color": "G", "entered_this_turn": True}


def test_counters_only_green_creatures_that_entered_this_turn():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    land = GameObject(card=Card(id="or", name="Oran-Rief, the Vastwood", type_line="Land"),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    land.controller_id = p1.id
    eng.state.add_to_battlefield(land)
    bind_from_catalogue(land)

    fresh_green = _cre(eng, "g1", "Elf", ["G"], p1.id)
    old_green = _cre(eng, "g2", "Bear", ["G"], p1.id)
    old_green.turn_entered = -5
    fresh_red = _cre(eng, "r1", "Goblin", ["R"], p1.id)
    fresh_green_opp = _cre(eng, "g3", "Wolf", ["G"], p2.id)  # "each green creature" — not just yours
    eng.recompute_continuous_effects()

    for e in land.activated_abilities[0].effects:
        e.source = land
        e.apply(eng.rules.context)
    eng.resolve_until_stable()

    assert fresh_green.counters.get("+1/+1", 0) == 1
    assert fresh_green_opp.counters.get("+1/+1", 0) == 1
    assert old_green.counters.get("+1/+1", 0) == 0
    assert fresh_red.counters.get("+1/+1", 0) == 0

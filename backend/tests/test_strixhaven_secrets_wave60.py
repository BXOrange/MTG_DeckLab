"""Secrets of Strixhaven — playability batch, wave 60 (PAR-60).

Woe Strider — new ``GameObject.cast_via_escape`` flag (stamped at the Escape
cast site, like ``cast_via_flashback``) + a ``cast_via_escape`` condition
key; "~ escapes with two +1/+1 counters on it" is an ETB add_counters gated
on it.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def test_woe_strider_registered_and_binds():
    assert is_registered("Woe Strider")
    specs = _REGISTRY["woe strider"]()
    assert len(specs) == 3
    src = GameObject(card=Card(id="ws", name="Woe Strider", type_line="Creature — Horror",
                             is_creature=True, power=3, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)
    counter_spec = specs[1]
    assert counter_spec.effects[0].type == "add_counters"
    assert counter_spec.effects[0].condition == {"cast_via_escape": True}


def _enter(eng, via_escape):
    p1 = eng.state.players[0]
    ws = GameObject(card=Card(id=f"ws{via_escape}", name="Woe Strider",
                             type_line="Creature — Horror", is_creature=True,
                             power=3, toughness=2),
                    owner_id=p1.id, zone=Zone.BATTLEFIELD)
    ws.controller_id = p1.id
    ws.cast_via_escape = via_escape
    eng.state.add_to_battlefield(ws)
    bind_from_catalogue(ws)
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=ws.instance_id,
                                   controller_id=p1.id))
    eng.resolve_until_stable()
    return ws


def test_escapes_with_two_counters_only_when_cast_via_escape():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    escaped = _enter(eng, True)
    plain = _enter(eng, False)
    assert escaped.counters.get("+1/+1", 0) == 2
    assert plain.counters.get("+1/+1", 0) == 0
    # both made a Goat token
    assert len([o for o in eng.state.battlefield if o.is_token]) == 2

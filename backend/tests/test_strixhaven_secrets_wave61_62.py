"""Secrets of Strixhaven — playability batch, waves 61-62 (PAR-60).

wave 61: Nexus Mentality — ``MoveCountersEffect.move_all_kinds`` +
         ``RemoveCountersEffect.draw_per_removed``.
wave 62: Open the Way — new ``RulesEngine.reveal_until_matching`` (the
         `card_query`-predicate sibling of ``reveal_until_creature_type``)
         + a ``reveal_until`` effect.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _bf(eng, cid, name, ctrl, **kw):
    obj = GameObject(card=Card(id=cid, name=name, type_line="Creature — X", is_creature=True,
                              power=1, toughness=1, **kw),
                     owner_id=ctrl, zone=Zone.BATTLEFIELD)
    obj.controller_id = ctrl
    eng.state.add_to_battlefield(obj)
    return obj


def test_nexus_mentality_registered():
    assert is_registered("Nexus Mentality")
    spec = _REGISTRY["nexus mentality"]()[0]
    spec.validate()
    opts = spec.modes["options"]
    assert opts[0][0].params["move_all_kinds"] is True
    assert opts[1][0].params["draw_per_removed"] is True
    assert spec.modes["or_both"] is True


def test_move_all_kinds_and_remove_all_then_draw():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.players[0]
    for i in range(10):
        p1.library.append(GameObject(card=Card(id=f"l{i}", name=f"L{i}", type_line="Instant"),
                                     owner_id=p1.id, zone=Zone.LIBRARY))
    a = _bf(eng, "a", "A", p1.id)
    b = _bf(eng, "b", "B", p1.id)
    a.counters["+1/+1"] = 3
    a.counters["charge"] = 2

    src = GameObject(card=Card(id="nm", name="Nexus Mentality", type_line="Instant"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id

    mv = EffectRegistry.create("move_counters", {"move_all_kinds": True})
    mv.source = src
    mv.apply(eng.rules.context, targets=[a, b])
    assert dict(a.counters) == {} or all(v == 0 for v in a.counters.values())
    assert b.counters["+1/+1"] == 3 and b.counters["charge"] == 2

    rm = EffectRegistry.create("remove_counters", {"target_kind": "nonland_permanent_you_control",
                                                   "draw_per_removed": True})
    rm.source = src
    before = len(p1.hand)
    rm.apply(eng.rules.context, targets=[b])
    assert len(p1.hand) - before == 5  # 3 + 2 counters removed
    assert all(v == 0 for v in b.counters.values())


def test_open_the_way_reveals_until_x_lands_onto_battlefield_tapped():
    assert is_registered("Open the Way")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.players[0]
    for nm, tl in [("For", "Basic Land — Forest"), ("Bolt", "Instant"),
                   ("Isl", "Basic Land — Island"), ("Mtn", "Basic Land — Mountain"),
                   ("Shock", "Instant"), ("Path", "Instant"),
                   ("Plains", "Basic Land — Plains")]:
        p1.library.append(GameObject(card=Card(id=nm, name=nm, type_line=tl),
                                     owner_id=p1.id, zone=Zone.LIBRARY))
    hits = eng.rules.reveal_until_matching(p1, {"type": "land"}, count=2,
                                           hit_destination="battlefield", tapped=True,
                                           rest_destination="library_bottom_random")
    assert len(hits) == 2
    lands = [o for o in eng.state.battlefield
             if "land" in o.card.type_line.lower() and o.controller_id == p1.id]
    assert len(lands) == 2
    assert all(o.tapped for o in lands)
    assert len(p1.library) == 5

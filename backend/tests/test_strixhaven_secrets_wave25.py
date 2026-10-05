"""Secrets of Strixhaven — playability batch, wave 25 (PAR-60).

Witherbloom "Pestilence": Eldrazi Spawn / devour token payoffs, recursion,
and the sacrifice tail, hand-authored in `game/card_registry/commander_cards.py`.
Engine: ``plus_one_counters_on_source`` `continuous.count_selector`;
``opponent_life_at_most`` `static_conditions` kind.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE25 = [
    "Awakening Zone", "Pawn of Ulamog", "Mycoloth", "Ribtruss Roaster",
    "Beledros Witherbloom", "Haywire Mite", "Bloodghast", "Nether Traitor",
    "Deadly Brew",
]


@pytest.mark.parametrize("name", WAVE25)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player, [p for p in eng.state.players
                                         if p.id != eng.state.active_player.id][0]


def _mk(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", "").replace(",", ""), name=name,
                             type_line=tl, **kw), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_mycoloth_makes_a_saproling_per_counter():
    eng, p1, _ = _eng()
    myco = _mk(eng, p1.id, "Mycoloth", "Creature — Fungus", is_creature=True,
              power=0, toughness=0)
    myco.counters["+1/+1"] = 4
    spec = _REGISTRY["mycoloth"]()[0]
    effs = build_effects(spec.effects, myco)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    saps = [o for o in eng.state.battlefield if o.card.name == "Saproling"]
    assert len(saps) == 4


def test_bloodghast_haste_tracks_opponent_life():
    from mtg_analyzer.game import static_conditions
    eng, p1, p2 = _eng()
    cond = {"kind": "opponent_life_at_most", "amount": 10}
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    p2.life = 9
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True


def test_bloodghast_haste_static_is_conditional_on_bind():
    eng, p1, p2 = _eng()
    bg = _mk(eng, p1.id, "Bloodghast", "Creature — Vampire Spirit", is_creature=True,
             power=2, toughness=1)
    statics = [e for spec in _REGISTRY["bloodghast"]()
               if spec.ability_kind == "static" for e in spec.effects]
    bg.static_effects.extend(build_effects(statics, bg))
    eng.recompute_continuous_effects()
    assert "cant_block" in bg.granted_keywords
    assert "haste" not in bg.granted_keywords  # opp at 20
    p2.life = 5
    eng.recompute_continuous_effects()
    assert "haste" in bg.granted_keywords

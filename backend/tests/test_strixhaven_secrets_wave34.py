"""Secrets of Strixhaven — playability batch, wave 34 (PAR-60).

Mixed singletons hand-authored in `game/ability_catalogue/entries_019.py`.
Engine: binder predicate ``defender_is_you`` (Mangara / Tomik's "attacking
you" `PLAYER_ATTACKED` gate).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE34 = ["Pest Infestation", "Excava, the Risen Past", "Mangara, the Diplomat",
          "Tomik, Wielder of Law"]


@pytest.mark.parametrize("name", WAVE34)
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


def test_defender_is_you_gate():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    src = GameObject(card=Card(id="mg", name="Mangara, the Diplomat",
                              type_line="Creature — Human Cleric", is_creature=True),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    ability = next(bind_ability(s, src) for s in _REGISTRY["mangara, the diplomat"]()
                   if s.trigger and s.trigger.get("defender_is_you"))
    # opponent attacks p1 with 2 -> fires
    assert ability.condition({"attacking_player_id": p2.id, "defending_player_id": p1.id,
                              "count": 2}, eng.rules.context) is True
    # opponent attacks p1 with 1 -> no
    assert ability.condition({"attacking_player_id": p2.id, "defending_player_id": p1.id,
                              "count": 1}, eng.rules.context) is False
    # opponent attacks someone else with 2 -> no
    assert ability.condition({"attacking_player_id": p2.id, "defending_player_id": "p3",
                              "count": 2}, eng.rules.context) is False


def test_pest_infestation_makes_twice_x_pests():
    from mtg_analyzer.game.effect_binder import build_effects
    from mtg_analyzer.game.effects import GameContext
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="pi", name="Pest Infestation", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    src.x_paid = 3
    tok_spec = next(e for spec in _REGISTRY["pest infestation"]()
                    for e in spec.effects if e.type == "create_token")
    effs = build_effects([tok_spec], src)
    eng.rules._substitute_x(effs, 3)  # x_multiplier reads source.x_paid
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    pests = [o for o in eng.state.battlefield if o.card.name == "Pest"]
    assert len(pests) == 6

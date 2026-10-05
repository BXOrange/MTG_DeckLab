"""Secrets of Strixhaven — playability batch, wave 33 (PAR-60).

Quandrix "your first spell with {X} in its mana cost each turn" trigger family,
hand-authored in `game/card_registry/commander_cards.py`. Engine:
`GameState.cast_x_spell_this_turn` per-turn set + `SPELL_CAST` ``first_x_spell``
flag + binder predicate ``first_x_spell``; count_selector
``study_counters_on_source``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE33 = ["Zimone, Infinite Analyst", "Owlin Spiralmancer",
          "Nev, the Practical Dean", "Lattice Library"]


@pytest.mark.parametrize("name", WAVE33)
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


def test_first_x_spell_flag_true_only_for_first_x_cast_this_turn():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player

    def _casts():
        return [e.data for e in eng.state.event_log if e.type == EventType.SPELL_CAST]

    def _cast(cid, cost):
        o = GameObject(card=Card(id=cid, name=cid, type_line="Sorcery",
                                 mana_cost_string=cost),
                       owner_id=p1.id, zone=Zone.HAND)
        o.controller_id = p1.id
        p1.hand.append(o)
        p1.mana_pool.add_many({"R": 3})
        eng.rules.cast_spell(p1, o, [], x=0)

    _cast("x1", "{X}{R}")
    _cast("plain", "{R}")
    _cast("x2", "{X}{R}")
    casts = _casts()
    by = {c["spell"]: c for c in casts}
    assert by["x1"]["first_x_spell"] is True
    assert by["plain"]["first_x_spell"] is False
    assert by["x2"]["first_x_spell"] is False   # already cast an {X} spell


def test_nev_static_grants_trample_to_countered_creatures():
    from mtg_analyzer.game.binding.core import build_effects
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    nev = GameObject(card=Card(id="nev", name="Nev, the Practical Dean",
                              type_line="Creature — Merfolk", is_creature=True),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    nev.controller_id = p1.id
    eng.state.add_to_battlefield(nev)
    statics = [e for spec in _REGISTRY["nev, the practical dean"]()
               if spec.ability_kind == "static" for e in spec.effects]
    nev.static_effects.extend(build_effects(statics, nev))

    plain = GameObject(card=Card(id="pl", name="Plain", type_line="Creature — Bear",
                                is_creature=True, power=2, toughness=2),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
    plain.controller_id = p1.id
    eng.state.add_to_battlefield(plain)
    counted = GameObject(card=Card(id="ct", name="Counted", type_line="Creature — Bear",
                                  is_creature=True, power=2, toughness=2),
                         owner_id=p1.id, zone=Zone.BATTLEFIELD)
    counted.controller_id = p1.id
    counted.counters["+1/+1"] = 1
    eng.state.add_to_battlefield(counted)

    eng.recompute_continuous_effects()
    assert "trample" in counted.granted_keywords
    assert "trample" not in plain.granted_keywords

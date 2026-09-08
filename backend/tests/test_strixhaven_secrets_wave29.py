"""Secrets of Strixhaven — playability batch, wave 29 (PAR-60).

Quandrix charge-counter / {X}-matters singletons, hand-authored in
`game/ability_catalogue/entries_019.py`. Engine: the `SPELL_CAST` event now
carries ``has_x`` ("{X}" in the printed mana cost); binder predicate
``spell_has_x`` reads it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE29 = ["Astral Cornucopia", "Elementalist's Palette", "Silkguard"]


@pytest.mark.parametrize("name", WAVE29)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Artifact"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_spell_cast_event_carries_has_x():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player

    def _last_cast():
        casts = [e for e in eng.state.event_log if e.type == EventType.SPELL_CAST]
        return casts[-1].data if casts else {}

    x_spell = GameObject(card=Card(id="xs", name="Fireball", type_line="Sorcery",
                                   mana_cost_string="{X}{R}"),
                         owner_id=p1.id, zone=Zone.HAND)
    x_spell.controller_id = p1.id
    p1.hand.append(x_spell)
    p1.mana_pool.add_many({"R": 1})
    eng.rules.cast_spell(p1, x_spell, [], x=0)
    assert _last_cast().get("has_x") is True

    plain = GameObject(card=Card(id="ps", name="Shock", type_line="Instant",
                                 mana_cost_string="{R}"),
                       owner_id=p1.id, zone=Zone.HAND)
    plain.controller_id = p1.id
    p1.hand.append(plain)
    p1.mana_pool.add_many({"R": 1})
    eng.rules.cast_spell(p1, plain, [])
    assert _last_cast().get("has_x") is False


def test_elementalists_palette_x_cast_trigger_predicate():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="ep", name="Elementalist's Palette", type_line="Artifact"),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    trig = next(s for s in _REGISTRY["elementalist's palette"]() if s.ability_kind == "triggered")
    ability = bind_ability(trig, src)
    assert ability.condition({"player_id": p1.id, "has_x": True}, eng.rules.context) is True
    assert ability.condition({"player_id": p1.id, "has_x": False}, eng.rules.context) is False

"""Smoldering Egg // Ashmouth Dragon (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Smoldering Egg // Ashmouth Dragon'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def _main(engine):
    for _ in range(10):
        if engine.state.current_step == "main1": return
        engine.advance_step()


def _cast(engine, name, mana, targets=None):
    player = engine.state.players[0]
    spell = _card(engine, name, zone=Zone.HAND)
    player.mana_pool.add_many(mana)
    engine.cast_spell(player, spell, targets=targets)
    engine.resolve_until_stable()
    return spell


def test_end_to_end():
    engine = _game()
    player, opponent = engine.state.players
    egg = _card(engine, NAME)
    engine.rules.add_counters(egg, 1, "shield")
    _main(engine)
    _cast(engine, "Lightning Bolt", {"R": 1}, [opponent])
    _cast(engine, "Divination", {"U": 1, "C": 2})
    assert egg.counters.get("ember") == 4 and not egg.transformed
    _cast(engine, "Divination", {"U": 1, "C": 2})
    assert egg.transformed and egg.name == "Ashmouth Dragon"
    assert "ember" not in egg.counters and egg.counters.get("shield") == 1
    _cast(engine, "Lightning Bolt", {"R": 1}, [opponent])
    if engine.state.pending_choice:
        engine.resolve_pending_choice("p2")
        engine.resolve_until_stable()
    assert opponent.life == 12


def test_free_spell_adds_zero_embers_and_creature_spell_does_not_trigger():
    engine = _game()
    player = engine.state.players[0]
    egg = _card(engine, NAME)
    engine.rules.add_counters(egg, 6, "ember")
    free = _card(engine, "Divination", zone=Zone.HAND)
    engine.rules.cast_without_paying(player, free)
    engine.resolve_until_stable()
    assert egg.counters.get("ember") == 6 and not egg.transformed
    _main(engine)
    _cast(engine, "Grizzly Bears", {"G": 1, "C": 1})
    assert egg.counters.get("ember") == 6 and not egg.transformed

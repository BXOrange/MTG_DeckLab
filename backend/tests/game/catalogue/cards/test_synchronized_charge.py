"""Synchronized Charge (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Synchronized Charge'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['spell_effect', 'keyword']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


@pytest.mark.parametrize("count", [1, 2])
def test_end_to_end(count):
    engine = _game()
    player = engine.state.players[0]
    creatures = [_card(engine, "Grizzly Bears") for _ in range(2)]
    plain = _card(engine, "Grizzly Bears")
    premarked = _card(engine, "Grizzly Bears")
    engine.rules.add_counters(premarked, 1, "shield")
    spell = _card(engine, NAME, zone=Zone.HAND)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add_many({"G": 1, "C": 1})
    engine.cast_spell(player, spell, targets=creatures[:count])
    engine.resolve_until_stable()
    assert sum(o.counters.get("+1/+1", 0) for o in creatures) == 2
    for obj in creatures[:count] + [premarked]:
        assert {"vigilance", "trample"} <= obj.granted_keywords
    assert "vigilance" not in plain.granted_keywords

"""Peel from Reality (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Peel from Reality'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


def test_end_to_end():
    engine = _game()
    player = engine.state.players[0]
    mine = _card(engine, "Grizzly Bears")
    theirs = _card(engine, "Grizzly Bears", player="p2")
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"U": 1, "C": 1})
    engine.cast_spell(player, spell, target_groups=[[mine], [theirs]])
    engine.resolve_until_stable()
    assert mine in player.hand
    assert theirs in engine.state.players[1].hand

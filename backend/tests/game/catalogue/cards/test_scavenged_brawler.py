"""Scavenged Brawler (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Scavenged Brawler'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


def test_end_to_end():
    engine = _game()
    player = engine.state.players[0]
    brawler = _card(engine, NAME, zone=Zone.GRAVEYARD)
    bear = _card(engine, "Grizzly Bears")
    player.mana_pool.add("C", 5)
    ability = brawler.activated_abilities[0]
    assert not engine.can_activate(player, brawler, ability)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add("C", 5)
    assert engine.can_activate(player, brawler, ability)
    engine.activate_ability(player, brawler, targets=[bear])
    assert brawler.zone == Zone.EXILE
    engine.resolve_until_stable()
    assert bear.counters == {"+1/+1": 4, "flying": 1, "vigilance": 1, "trample": 1, "lifelink": 1}
    engine.recompute_continuous_effects()
    assert {"flying", "vigilance", "trample", "lifelink"} <= bear.granted_keywords
    assert bear.power == bear.toughness == 6
    assert not engine.can_activate(player, brawler, ability)


def test_battlefield_activation_is_refused():
    engine = _game()
    player = engine.state.players[0]
    brawler = _card(engine, NAME)
    player.mana_pool.add("C", 5)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    assert not engine.can_activate(player, brawler, brawler.activated_abilities[0])

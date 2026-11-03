"""Zameck Guildmage (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Zameck Guildmage'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['activated', 'activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


def test_end_to_end():
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    player = engine.state.players[0]
    guildmage = _card(engine, NAME)
    player.mana_pool.add_many({"G": 3, "U": 3})
    for _ in range(2):
        engine.activate_ability(player, guildmage, 0)
        engine.resolve_until_stable()
    bear = _card(engine, "Grizzly Bears", zone=Zone.HAND)
    engine.rules.cast_without_paying(player, bear)
    engine.resolve_until_stable()
    assert bear.counters.get("+1/+1") == 2
    hand_before = len(player.hand)
    engine.activate_ability(player, guildmage, 1)
    engine.resolve_until_stable()
    assert bear.counters.get("+1/+1") == 1
    assert len(player.hand) == hand_before + 1
    engine.rules.destroy(guildmage)
    token_card = synthesize_token_card("Bear", power=2, toughness=2)
    mine = engine.rules.create_token("p1", token_card, 1)[0]
    enemy = engine.rules.create_token("p2", token_card, 1)[0]
    assert mine.counters.get("+1/+1") == 2
    assert not enemy.counters
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.active_player.id == "p2": break
    late = engine.rules.create_token("p1", token_card, 1)[0]
    assert not late.counters

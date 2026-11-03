"""Nezumi Graverobber // Nighteyes the Desecrator (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Nezumi Graverobber // Nighteyes the Desecrator'


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
    player, opponent = engine.state.players
    rat = _card(engine, NAME)
    first = _card(engine, "Grizzly Bears", player="p2", zone=Zone.GRAVEYARD)
    second = _card(engine, "Forest", player="p2", zone=Zone.GRAVEYARD)
    player.mana_pool.add_many({"B": 2, "C": 2})
    engine.activate_ability(player, rat, targets=[first])
    engine.resolve_until_stable()
    assert first.zone == Zone.EXILE
    assert not rat.flipped
    engine.activate_ability(player, rat, targets=[second])
    engine.resolve_until_stable()
    assert second.zone == Zone.EXILE
    assert rat.flipped and rat.name == "Nighteyes the Desecrator"
    assert len(rat.activated_abilities) == 1
    creature = _card(engine, "Grizzly Bears", player="p2", zone=Zone.GRAVEYARD)
    player.mana_pool.add_many({"B": 1, "C": 4})
    engine.activate_ability(player, rat, targets=[creature])
    engine.resolve_until_stable()
    assert creature.zone == Zone.BATTLEFIELD and creature.controller_id == "p1"


def test_does_not_target_own_graveyard_or_flip_after_illegal_target():
    engine = _game()
    player = engine.state.players[0]
    rat = _card(engine, NAME)
    mine = _card(engine, "Forest", zone=Zone.GRAVEYARD)
    theirs = _card(engine, "Forest", player="p2", zone=Zone.GRAVEYARD)
    player.mana_pool.add_many({"B": 1, "C": 1})
    with pytest.raises(ValueError):
        engine.activate_ability(player, rat, targets=[mine])
    engine.activate_ability(player, rat, targets=[theirs])
    engine.rules.return_to_hand(theirs)
    engine.resolve_until_stable()
    assert not rat.flipped

"""Sarevok's Tome (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = "Sarevok's Tome"


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['triggered', 'activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("cast", [True, False])
def test_end_to_end(cast):
    engine = _game()
    player, opponent = engine.state.players
    tome = _card(engine, NAME)
    player.mana_pool.add("C", 3)
    ability = tome.activated_abilities[0]
    assert not engine.can_activate(player, tome, ability)
    opponent.completed_dungeons.append("Undercity")
    assert not engine.can_activate(player, tome, ability)
    player.completed_dungeons.append("Lost Mine of Phandelver")
    assert engine.can_activate(player, tome, ability)
    creature = _card(engine, "Grizzly Bears", zone=Zone.LIBRARY)
    land = _card(engine, "Forest", zone=Zone.LIBRARY)
    engine.activate_ability(player, tome)
    engine.resolve_until_stable()
    assert land.zone == creature.zone == Zone.EXILE
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    if cast:
        engine.play_resolution_card(player, creature)
    else:
        engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert creature.zone == (Zone.BATTLEFIELD if cast else Zone.EXILE)
    assert land.zone == Zone.EXILE
    assert tome.tapped

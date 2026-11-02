"""Prosper, Tome-Bound (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Prosper, Tome-Bound'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:3] == ['triggered', 'triggered', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def test_end_to_end():
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _end_step, _zone_card
    engine = _game()
    player = engine.state.players[0]
    prosper = _card(engine, NAME)
    land = _card(engine, "Forest", zone=Zone.LIBRARY)
    _end_step(engine)
    engine.resolve_until_stable()
    assert land.zone == Zone.EXILE
    assert land.instance_id in engine.state.temp_play_permissions
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.active_player.id == "p1" and engine.state.current_step == "main1": break
    engine.play_land(player, land)
    engine.resolve_until_stable()
    treasures = [o for o in engine.state.battlefield if o.is_token and o.name == "Treasure"]
    assert len(treasures) == 1
    exiled_spell = _card(engine, "Grizzly Bears", zone=Zone.EXILE)
    engine.rules._grant_temp_play_permission(exiled_spell, player, prosper.name, True, None)
    player.mana_pool.add_many({"G": 1, "C": 1})
    engine.cast_spell(player, exiled_spell)
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token and o.name == "Treasure"]) == 2
    spell = _card(engine, "Grizzly Bears", zone=Zone.HAND)
    engine.rules.cast_without_paying(player, spell)
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token and o.name == "Treasure"]) == 2

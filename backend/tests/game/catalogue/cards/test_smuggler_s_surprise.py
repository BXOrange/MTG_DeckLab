"""Smuggler's Surprise (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = "Smuggler's Surprise"


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert len(obj.spell_modes) == 3


def _main(engine):
    for _ in range(10):
        if engine.state.current_step == "main1": return
        engine.advance_step()


def test_mill_recovers_only_up_to_two_of_these_creatures_and_lands():
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _zone_card
    engine = _game()
    player = engine.state.players[0]
    old = _card(engine, "Grizzly Bears", zone=Zone.GRAVEYARD)
    picks = [_zone_card(engine, name, type_line, "p1", Zone.LIBRARY) for name,type_line in [
        ("New creature", "Creature"), ("New land", "Land"), ("New instant", "Instant"), ("New artifact", "Artifact")]]
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(player, spell, mode=[0])
    engine.resolve_until_stable()
    offered = {o["id"] for o in engine.state.pending_choice["options"]}
    assert str(old.instance_id) not in offered
    assert all(str(o.instance_id) not in offered for o in picks[2:])
    for obj in picks[:2]:
        engine.resolve_pending_choice(str(obj.instance_id))
        engine.resolve_until_stable()
    assert all(obj in player.hand for obj in picks[:2])
    assert all(obj in player.graveyard for obj in [old, *picks[2:]])


def test_put_two_creatures_and_protect_only_large_creatures_in_printed_order():
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _zone_card
    engine = _game()
    player = engine.state.players[0]
    small = _card(engine, "Grizzly Bears")
    big = _zone_card(engine, "Big", "Creature", "p1", Zone.HAND)
    big.card.power = big.card.toughness = 4
    big2 = _zone_card(engine, "Big2", "Creature", "p1", Zone.HAND)
    big2.card.power = big2.card.toughness = 5
    land = _card(engine, "Forest", zone=Zone.HAND)
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"G": 2, "C": 5})
    engine.cast_spell(player, spell, mode=[1, 2])
    engine.resolve_until_stable()
    for obj in [big, big2]:
        engine.resolve_pending_choice(str(obj.instance_id))
        engine.resolve_until_stable()
    assert land.zone == Zone.HAND
    for obj in [big, big2]:
        assert obj.zone == Zone.BATTLEFIELD
        assert {"hexproof", "indestructible"} <= obj.granted_keywords
    assert "indestructible" not in small.granted_keywords


def test_decline_milled_cards():
    engine = _game()
    player = engine.state.players[0]
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(player, spell, mode=[0])
    engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")
    assert not player.hand

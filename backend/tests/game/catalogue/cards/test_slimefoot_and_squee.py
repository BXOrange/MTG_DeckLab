"""Slimefoot and Squee (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Slimefoot and Squee'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['triggered', 'activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("pick", [False, True])
def test_end_to_end(pick):
    from mtg_analyzer.models.game.events import EventType
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    player = engine.state.players[0]
    slime = _card(engine, NAME, zone=Zone.GRAVEYARD)
    bear = _card(engine, "Grizzly Bears", zone=Zone.GRAVEYARD)
    sap = engine.rules.create_token("p1", synthesize_token_card("Saproling", power=1, toughness=1, subtypes=["Saproling"], colors=["G"]), 1)[0]
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add_many({"B": 1, "R": 1, "G": 1, "C": 1})
    entries = []
    engine.state.subscribe(lambda event: entries.append((slime.zone, bear.zone))
        if event.type == EventType.ENTERS_BATTLEFIELD and event.get("instance_id") == slime.instance_id else None)
    engine.activate_ability(player, slime, targets=[bear] if pick else [], sacrifice_choice=sap.instance_id)
    engine.resolve_until_stable()
    assert slime.zone == Zone.BATTLEFIELD
    assert bear.zone == (Zone.BATTLEFIELD if pick else Zone.GRAVEYARD)
    assert entries == [(Zone.BATTLEFIELD, Zone.BATTLEFIELD if pick else Zone.GRAVEYARD)]
    assert len([obj for obj in engine.state.battlefield if obj.is_token and "Saproling" in obj.card.type_line]) == 1


def test_cannot_target_self_or_return_a_new_graveyard_visit():
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    player = engine.state.players[0]
    slime = _card(engine, NAME, zone=Zone.GRAVEYARD)
    bear = _card(engine, "Grizzly Bears", zone=Zone.GRAVEYARD)
    sap = engine.rules.create_token("p1", synthesize_token_card("Saproling", power=1, toughness=1, subtypes=["Saproling"], colors=["G"]), 1)[0]
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add_many({"B": 1, "R": 1, "G": 1, "C": 1})
    with pytest.raises(ValueError):
        engine.activate_ability(player, slime, targets=[slime], sacrifice_choice=sap.instance_id)
    engine.activate_ability(player, slime, targets=[bear], sacrifice_choice=sap.instance_id)
    engine.rules.return_to_hand(slime)
    engine.rules.discard_specific(slime)
    engine.resolve_until_stable()
    assert slime.zone == Zone.GRAVEYARD and bear.zone == Zone.BATTLEFIELD

"""Highcliff Felidar (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = "Highcliff Felidar"


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
                                      controller_id=obj.controller_id))
    engine.resolve_until_stable()


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:1] == ["triggered"]


def test_enters_destroys_the_opponents_greatest_power_creature_only():
    engine = _game()
    felidar = _card(engine, NAME, zone=Zone.BATTLEFIELD)
    big = battlefield_object(engine, "p2", "Big", "Creature — Beast", is_creature=True, power=5, toughness=5)
    small = battlefield_object(engine, "p2", "Small", "Creature — Bear", is_creature=True, power=2, toughness=2)
    mine = battlefield_object(engine, "p1", "Mine", "Creature — Giant", is_creature=True, power=9, toughness=9)
    _enter(engine, felidar)
    assert big.zone == Zone.GRAVEYARD
    assert small.zone == Zone.BATTLEFIELD
    assert mine.zone == Zone.BATTLEFIELD  # "for each opponent": the controller's own creatures are never chosen


def test_opponent_with_no_creatures_is_skipped():
    engine = _game()
    felidar = _card(engine, NAME, zone=Zone.BATTLEFIELD)
    _enter(engine, felidar)
    assert felidar.zone == Zone.BATTLEFIELD

"""Soulherder (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Soulherder'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def test_end_to_end():
    from tests.support.catalogue import battlefield_object
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _zone_card
    engine = _game()
    herder = _card(engine, NAME)
    mine = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Bear2", "Creature", is_creature=True, power=2, toughness=2)
    relic = battlefield_object(engine, "p1", "Relic", "Artifact")
    grave = _zone_card(engine, "Dead Bear", "Creature", "p1", Zone.GRAVEYARD)
    for obj in [mine, theirs, relic, grave]:
        engine.rules.exile(obj)
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
    assert herder.counters.get("+1/+1") == 2


def test_departing_copy_uses_battlefield_creature_type():
    from tests.support.catalogue import battlefield_object
    engine = _game()
    herder = _card(engine, NAME)
    copy = battlefield_object(engine, "p1", "Relic", "Artifact")
    bear = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    engine.rules.become_copy(copy, bear)
    engine.recompute_continuous_effects()
    assert copy.is_creature
    engine.rules.exile(copy)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert herder.counters.get("+1/+1") == 1

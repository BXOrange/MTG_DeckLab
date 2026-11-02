"""Gisa, the Hellraiser (hand-authored)."""

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = 'Gisa, the Hellraiser'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:3] == ['triggered', 'static', 'static']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("type_line, owner, expect_buff", [
    ("Creature — Zombie", "p1", True),
    ("Creature — Skeleton", "p1", True),
    ("Creature — Zombie Skeleton", "p1", True),
    ("Creature — Zombie", "p2", False),
    ("Creature — Human", "p1", False),
])
def test_anthem_and_menace_follow_subtype_and_control(type_line, owner, expect_buff):
    engine = _game()
    _card(engine, NAME)
    target = battlefield_object(engine, owner, "Target", type_line, is_creature=True, power=2, toughness=2)
    continuous.recompute(engine.state)
    if expect_buff:
        assert (target.power, target.toughness) == (3, 3)
        assert combat.has(target, "menace")
    else:
        assert (target.power, target.toughness) == (2, 2)
        assert not combat.has(target, "menace")


def test_zombie_skeleton_is_buffed_once():
    engine = _game()
    _card(engine, NAME)
    both = battlefield_object(engine, "p1", "Both", "Creature — Zombie Skeleton", is_creature=True, power=2, toughness=2)
    continuous.recompute(engine.state)
    assert (both.power, both.toughness) == (3, 3)

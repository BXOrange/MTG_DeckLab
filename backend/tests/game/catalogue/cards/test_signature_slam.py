"""Signature Slam (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Signature Slam'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


def test_end_to_end():
    from tests.support.catalogue import battlefield_object
    engine = _game()
    player = engine.state.players[0]
    first = _card(engine, "Grizzly Bears")
    marked = _card(engine, "Grizzly Bears")
    engine.rules.add_counters(marked, 1, "shield")
    plain = _card(engine, "Grizzly Bears")
    enemy = _card(engine, "Grizzly Bears", player="p2")
    engine.rules.add_counters(enemy, 1, "+1/+1")
    victim = battlefield_object(engine, "p2", "Victim", "Creature", is_creature=True, power=1, toughness=10)
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(player, spell, target_groups=[[first], [victim]])
    engine.resolve_until_stable()
    assert first.counters.get("+1/+1") == 1
    assert victim.damage_marked == 5  # 3 from the newly modified target + 2 from shield-marked bear
    assert not plain.counters and enemy.damage_marked == 0

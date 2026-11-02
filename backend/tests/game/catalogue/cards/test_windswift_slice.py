"""Windswift Slice (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Windswift Slice'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


@pytest.mark.parametrize("power,expected", [(5, 3), (2, 0), (1, 0)])
def test_end_to_end(power, expected):
    from tests.support.catalogue import battlefield_object
    engine = _game()
    player = engine.state.players[0]
    dealer = battlefield_object(engine, "p1", "Dealer", "Creature", is_creature=True, power=power, toughness=5)
    victim = _card(engine, "Grizzly Bears", player="p2")
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(player, spell, target_groups=[[dealer], [victim]])
    engine.resolve_until_stable()
    elves = [o for o in engine.state.battlefield if o.is_token and "Elf" in o.card.type_line]
    assert len(elves) == expected
    assert all("Warrior" in o.card.type_line and o.power == o.toughness == 1 for o in elves)
    assert dealer.damage_marked == 0

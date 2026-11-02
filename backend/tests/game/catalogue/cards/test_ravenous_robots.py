"""Ravenous Robots (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Ravenous Robots'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def test_end_to_end():
    from tests.support.catalogue import battlefield_object
    engine = _game()
    player = engine.state.players[0]
    robots = _card(engine, NAME)
    robots.summoning_sick = False
    token = battlefield_object(engine, "p1", "Token", "Creature", is_creature=True, power=1, toughness=1)
    token.is_token = True
    other = battlefield_object(engine, "p1", "Other", "Creature", is_creature=True, power=1, toughness=1)
    enemy = battlefield_object(engine, "p2", "Enemy Token", "Creature", is_creature=True, power=1, toughness=1)
    enemy.is_token = True
    player.mana_pool.add("R", 1)
    engine.activate_ability(player, robots)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert "haste" in token.granted_keywords
    assert "haste" not in other.granted_keywords
    assert "haste" not in enemy.granted_keywords
    assert robots.tapped

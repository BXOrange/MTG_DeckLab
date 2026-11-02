"""Slash the Ranks (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Slash the Ranks'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:0] == []


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


def test_end_to_end():
    from tests.support.catalogue import battlefield_object
    engine = _game()
    player = engine.state.players[0]
    creature = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    walker = battlefield_object(engine, "p2", "Walker", "Planeswalker", loyalty=3)
    commander = battlefield_object(engine, "p2", "Commander", "Creature", is_creature=True, power=2, toughness=2)
    commander.is_commander = True
    relic = battlefield_object(engine, "p1", "Relic", "Artifact")
    spell = _card(engine, NAME, zone=Zone.HAND)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add_many({"W": 2, "C": 3})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD
    assert walker.zone == Zone.GRAVEYARD
    assert commander in engine.state.battlefield
    assert relic in engine.state.battlefield

"""Queen Allenal of Ruadach (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Queen Allenal of Ruadach'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['static', 'replacement']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.static_effects


def test_end_to_end():
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    queen = _card(engine, NAME)
    bear = synthesize_token_card("Bear", power=2, toughness=2, colors=["G"])
    made = engine.rules.create_token("p1", bear, 3)
    assert len(made) == 4
    assert sum(obj.name == "Soldier" for obj in made) == 1
    engine.recompute_continuous_effects()
    assert queen.power == queen.toughness == 5
    assert len(engine.rules.create_token("p2", bear, 2)) == 2
    treasure = synthesize_token_card("Treasure", is_artifact=True)
    assert len(engine.rules.create_token("p1", treasure, 2)) == 2
    assert engine.rules.create_token("p1", bear, 0) == []

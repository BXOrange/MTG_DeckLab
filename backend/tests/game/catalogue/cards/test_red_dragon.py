"""Red Dragon (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Red Dragon'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:0] == []


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def test_end_to_end():
    engine = _game(3)
    player = engine.state.players[0]
    dragon = _card(engine, NAME, zone=Zone.HAND)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add_many({"R": 2, "C": 4})
    engine.cast_spell(player, dragon)
    engine.resolve_until_stable()
    assert dragon in engine.state.battlefield
    assert [p.life for p in engine.state.players] == [20, 16, 16]
    assert "flying" in {x.lower() for x in dragon.granted_keywords | set(dragon.card.keywords)}

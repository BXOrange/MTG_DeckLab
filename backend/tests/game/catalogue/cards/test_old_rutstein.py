"""Old Rutstein (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Old Rutstein'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("type_line,expected", [
    ("Land", ["Treasure"]), ("Creature", ["Insect"]),
    ("Artifact", ["Blood"]), ("Land Creature", ["Insect", "Treasure"]),
    (None, []),
])
def test_end_to_end(type_line, expected):
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _zone_card
    engine = _game()
    player = engine.state.players[0]
    player.library.clear()
    if type_line:
        milled = _zone_card(engine, "Top", type_line, "p1", Zone.LIBRARY)
    rutstein = _card(engine, NAME, zone=Zone.HAND)
    engine.rules.cast_without_paying(player, rutstein)
    engine.resolve_until_stable()
    assert sorted(obj.name for obj in engine.state.battlefield if obj.is_token) == expected
    if type_line:
        assert milled in player.graveyard

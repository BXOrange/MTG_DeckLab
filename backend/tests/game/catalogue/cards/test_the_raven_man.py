"""The Raven Man (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'The Raven Man'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['activated', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


@pytest.mark.parametrize("discarder", [None, "p1", "p2"])
def test_end_to_end(discarder):
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _end_step
    engine = _game()
    raven = _card(engine, NAME)
    if discarder:
        card = _card(engine, "Grizzly Bears", player=discarder, zone=Zone.HAND)
        engine.rules.discard_specific(card)
    _end_step(engine)
    engine.resolve_until_stable()
    birds = [obj for obj in engine.state.battlefield if obj.is_token and obj.name == "Bird"]
    assert len(birds) == int(discarder is not None)
    if birds:
        engine.recompute_continuous_effects()
        assert {"flying", "cant_block"} <= birds[0].granted_keywords | {k.lower() for k in birds[0].card.keywords}

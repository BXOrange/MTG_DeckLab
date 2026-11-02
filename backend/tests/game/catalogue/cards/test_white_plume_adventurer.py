"""White Plume Adventurer (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'White Plume Adventurer'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:2] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("completed_by", [None, "p1", "p2"])
def test_end_to_end(completed_by):
    engine = _game()
    adventurer = _card(engine, NAME)
    bears = [_card(engine, "Grizzly Bears") for _ in range(2)]
    if completed_by:
        engine.state.player_by_id(completed_by).completed_dungeons.append("Lost Mine of Phandelver")
    for obj in [adventurer, *bears]: obj.tapped = True
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == "p2": break
    if completed_by == "p1":
        assert not engine.state.pending_choice
        assert all(not obj.tapped for obj in [adventurer, *bears])
    else:
        assert engine.state.pending_choice["kind"] == "choose_objects"
        engine.resolve_pending_choice(str(bears[0].instance_id))
        engine.resolve_until_stable()
        assert not bears[0].tapped and bears[1].tapped and adventurer.tapped

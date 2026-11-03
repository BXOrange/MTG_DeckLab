"""Nezumi Shortfang // Stabwhisker the Odious (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Nezumi Shortfang // Stabwhisker the Odious'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


@pytest.mark.parametrize("hand_count,flipped", [(0, True), (1, True), (2, False)])
def test_end_to_end(hand_count, flipped):
    engine = _game()
    player, opponent = engine.state.players
    rat = _card(engine, NAME)
    rat.summoning_sick = False
    for _ in range(hand_count): _card(engine, "Grizzly Bears", player="p2", zone=Zone.HAND)
    player.mana_pool.add_many({"B": 1, "C": 1})
    engine.activate_ability(player, rat, targets=[opponent])
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        assert engine.state.pending_choice["player_id"] == "p2"
        engine.resolve_pending_choice(str(opponent.hand[0].instance_id))
        engine.resolve_until_stable()
    assert len(opponent.hand) == max(0, hand_count-1)
    assert rat.flipped == flipped
    assert rat.tapped
    if flipped:
        assert rat.name == "Stabwhisker the Odious" and len(rat.triggered_abilities) == 1


@pytest.mark.parametrize("cards,loss", [(0,3), (1,2), (2,1), (3,0), (4,0)])
def test_flipped_upkeep_counts_the_active_opponents_hand(cards, loss):
    engine = _game()
    player, opponent = engine.state.players
    rat = _card(engine, NAME)
    assert engine.rules._flip_permanent(rat)
    for _ in range(cards): _card(engine, "Grizzly Bears", player="p2", zone=Zone.HAND)
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == "p2": break
    assert opponent.life == 20-loss
    assert player.life == 20

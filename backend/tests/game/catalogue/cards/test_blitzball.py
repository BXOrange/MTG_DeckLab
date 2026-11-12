"""Blitzball's mana and conditional tap/sacrifice draw ability."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase


def _board(legendary=True, creature=True):
    engine = game(players=3)
    main_phase(engine)
    ball = card(engine, "Blitzball")
    dealer = filler(engine, "Dealer", player="p2",
                    type_line=("Legendary " if legendary else "") + ("Creature — Human" if creature else "Artifact"),
                    power=2 if creature else None, toughness=3 if creature else None)
    return engine, engine.state.player_by_id("p1"), ball, dealer


def test_opponents_legendary_creature_hitting_another_opponent_enables_draw():
    engine, player, ball, dealer = _board()
    a, b = specs_for(ball.card), specs_for(ball.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.rules.deal_combat_damage([(engine.state.player_by_id("p3"), 2, dealer)])
    hand = len(player.hand)
    engine.activate_ability(player, ball)
    assert ball in player.graveyard and len(player.hand) == hand
    engine.resolve_until_stable()
    assert len(player.hand) == hand + 2


@pytest.mark.parametrize("legendary,creature,combat,recipient,amount", [
    (False, True, True, "p3", 2), (True, False, True, "p3", 2),
    (True, True, False, "p3", 2), (True, True, True, "p1", 2),
    (True, True, True, "p3", 0),
])
def test_nonqualifying_damage_does_not_enable_activation(legendary, creature, combat, recipient, amount):
    engine, player, ball, dealer = _board(legendary, creature)
    engine.rules.deal_damage(engine.state.player_by_id(recipient), amount, source=dealer, combat=combat)
    with pytest.raises(ValueError):
        engine.activate_ability(player, ball)
    assert ball.zone == Zone.BATTLEFIELD and not ball.tapped


def test_history_uses_legendary_status_at_damage_and_survives_departure_and_clone():
    engine, player, ball, dealer = _board()
    engine.rules.deal_combat_damage([(engine.state.player_by_id("p3"), 2, dealer)])
    engine.rules.exile(dealer)
    clone = GameEngine(engine.state.clone())
    cloned_player = clone.state.player_by_id("p1")
    clone.activate_ability(cloned_player, clone.state.find_object(ball.instance_id))
    clone.resolve_until_stable()
    assert len(cloned_player.hand) == 2 and not player.hand


def test_previous_turn_damage_does_not_enable_activation():
    engine, player, ball, dealer = _board()
    engine.rules.deal_combat_damage([(engine.state.player_by_id("p3"), 2, dealer)])
    engine.state.internal_turn.number += 1
    with pytest.raises(ValueError):
        engine.activate_ability(player, ball)


def test_mana_ability_still_works_without_combat_history():
    engine, player, ball, dealer = _board()
    produced = engine.tap_for_mana(player, ball, option_index=1)
    assert produced == {"U": 1} and ball.tapped
    assert ball.zone == Zone.BATTLEFIELD

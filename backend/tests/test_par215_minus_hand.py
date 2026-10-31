"""PAR-215 axis D: "X damage to that player, where X is N minus the number of cards in their hand" (RULE 107.1b).

Wheel of Torture / Rackling / Storm World: the upkeep player is "that player"; a negative X counts as 0.
"""
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, step


def _upkeep_damage(name, hand_size, upkeep_player):
    eng = game(library=5)
    card(eng, name)
    for i in range(hand_size):
        filler(eng, f"Spare{i}", type_line="Instant", player=upkeep_player, zone=Zone.HAND)
    life = eng.state.player_by_id(upkeep_player).life
    eng.state.active_player_index = [p.id for p in eng.state.players].index(upkeep_player)
    step(eng, "upkeep", player=upkeep_player)
    return life - eng.state.player_by_id(upkeep_player).life


def test_wheel_of_torture_scales_with_empty_hand():
    assert _upkeep_damage("Wheel of Torture", 1, "p2") == 2
    assert _upkeep_damage("Wheel of Torture", 0, "p2") == 3


def test_wheel_of_torture_deals_nothing_to_a_full_hand():
    assert _upkeep_damage("Wheel of Torture", 5, "p2") == 0


def test_wheel_of_torture_ignores_its_controllers_upkeep():
    assert _upkeep_damage("Wheel of Torture", 0, "p1") == 0

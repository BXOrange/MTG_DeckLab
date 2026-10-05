"""Life-gained conditions and selectors."""

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.continuous import count_selector
from tests.support.catalogue import two_player_game


def test_life_gained_this_turn_condition_and_selector():
    engine, player = two_player_game()
    condition = {"kind": "gained_life_this_turn"}
    assert static_conditions.condition_holds(condition, engine.state, None, player.id) is False
    assert count_selector(engine.state, player.id, "life_gained_this_turn") == 0
    engine.rules.gain_life(player, 3)
    assert static_conditions.condition_holds(condition, engine.state, None, player.id) is True
    assert count_selector(engine.state, player.id, "life_gained_this_turn") == 3

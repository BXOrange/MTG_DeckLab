"""Blossoming Bogbeast scales creatures with life gained."""

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from tests.support.catalogue import battlefield_object, two_player_game


def test_blossoming_bogbeast_pumps_by_life_gained():
    engine, player = two_player_game()
    bogbeast = battlefield_object(
        engine, player.id, "Blossoming Bogbeast", "Creature — Beast", is_creature=True, power=4, toughness=4,
    )
    other = battlefield_object(
        engine, player.id, "Buddy", "Creature — Bear", is_creature=True, power=2, toughness=2,
    )
    effects = build_effects(_REGISTRY["blossoming bogbeast"]()[0].effects, bogbeast)
    context = GameContext(state=engine.state, engine=engine.rules)
    for effect in effects:
        effect.apply(context, [])
    engine.recompute_continuous_effects()
    assert player.life == 22
    assert (bogbeast.power, bogbeast.toughness) == (6, 6)
    assert (other.power, other.toughness) == (4, 4)
    assert "trample" in other.granted_keywords

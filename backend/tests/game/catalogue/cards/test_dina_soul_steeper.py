"""Dina, Soul Steeper reads the sacrificed creature's power."""

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.parser.oracle.spec import EffectSpec
from tests.support.catalogue import battlefield_object, two_player_game


def test_dina_soul_steeper_pump_reads_sacrificed_power():
    engine, player = two_player_game()
    dina = battlefield_object(
        engine, player.id, "Dina, Soul Steeper", "Legendary Creature — Dryad Druid",
        is_creature=True, power=1, toughness=3,
    )
    dina.sacrificed_cost_power = 5
    effects = build_effects(
        [EffectSpec("pump", {"power": 0, "toughness": 0, "amount_from_count_selector": "sacrificed_cost_power", "amount_from_count_selector_axis": "power"})],
        dina,
    )
    context = GameContext(state=engine.state, engine=engine.rules)
    for effect in effects:
        effect.apply(context, [])
    engine.recompute_continuous_effects()
    assert (dina.power, dina.toughness) == (6, 3)

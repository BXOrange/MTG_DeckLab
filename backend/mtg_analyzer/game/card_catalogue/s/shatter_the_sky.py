from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shatter_the_sky() -> list[AbilitySpec]:
    """Each player who controls a creature with power 4 or greater draws a card.
    Then destroy all creatures."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("draw_each_player_with_creature_power", {"min_power": 4}),
        EffectSpec("destroy", {"selector": "all_creatures"}),
    ])]


register("Shatter the Sky", _shatter_the_sky)

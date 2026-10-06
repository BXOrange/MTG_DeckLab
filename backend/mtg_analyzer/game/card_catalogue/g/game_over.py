from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _game_over() -> list[AbilitySpec]:
    """A low life total enables the discount; destroy all creatures."""
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {"affects": "self", "generic": 2,
            "active_if": {"kind": "any_player_at_half_starting_life"}})]),
        AbilitySpec("spell_effect", [EffectSpec("destroy", {"selector": "all_creatures"})]),
    ]


register('Game Over', _game_over)

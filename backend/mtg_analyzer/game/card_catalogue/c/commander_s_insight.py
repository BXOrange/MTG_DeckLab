from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commanders_insight() -> list[AbilitySpec]:
    """Target player draws X cards plus an additional card for each time
    they've cast a commander from the command zone this game.

    Documented simplification: the "for each time *they've* cast a commander"
    count is read as *your* commander-cast tally
    (``commander_casts_this_game`` is always the resolving controller's) —
    exact when you target yourself, an approximation otherwise."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"target_kind": "player", "count": "x"}),
                EffectSpec("draw", {"target_kind": "player",
                                    "count_selector": "commander_casts_this_game"}),
            ],
        ),
    ]


register("Commander's Insight", _commanders_insight)

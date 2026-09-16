from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Oversimplify (per-player payoff from a mass exile) — PAR-60
# ===========================================================================
# New `oversimplify` effect: snapshot each player's total creature power,
# exile all creatures, then one Fractal token per player with that many
# +1/+1 counters.


def _oversimplify() -> list[AbilitySpec]:
    """Exile all creatures. Each player creates a 0/0 green and blue Fractal
    creature token and puts a number of +1/+1 counters on it equal to the
    total power of creatures they controlled that were exiled this way."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("oversimplify", {})],
        ),
    ]


register("Oversimplify", _oversimplify)

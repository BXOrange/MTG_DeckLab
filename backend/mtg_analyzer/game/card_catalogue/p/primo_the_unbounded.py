from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Primo, the Unbounded (twice-X entry counters + base-power-0
# combat-damage Fractal) — PAR-60
# ===========================================================================
# Clause 1 reuses `AddCountersEffect.x_multiplier` (Banquet Guests). Clause
# 2 reuses `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` with a new
# ``contributor_base_power_zero`` predicate + a `base0_combat_damage_fractal`
# effect. Trample folds in from the RULE 702 keyword catalogue.


def _primo_the_unbounded() -> list[AbilitySpec]:
    """Trample
    Primo enters with twice X +1/+1 counters on it.
    Whenever one or more creatures you control with base power 0 deal combat
    damage to a player, create a 0/0 green and blue Fractal creature token.
    Put a number of +1/+1 counters on it equal to the damage dealt."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"x_multiplier": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("base0_combat_damage_fractal", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
                "contributor_base_power_zero": True,
            },
        ),
    ]


register("Primo, the Unbounded", _primo_the_unbounded)

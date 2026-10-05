from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Witherbloom Pestilence: "life you gained this turn" + sacrifice
# ===========================================================================


def _mortality_spear() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if you gained life this turn.
    Destroy target nonland permanent."""
    MORTALITY_SPEAR_DISCOUNT = 2
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": MORTALITY_SPEAR_DISCOUNT,
                "active_if": {"kind": "gained_life_this_turn"},
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "nonland_permanent"})],
        ),
    ]


register("Mortality Spear", _mortality_spear)

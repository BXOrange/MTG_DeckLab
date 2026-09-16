from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Zimone's Hypothesis (odd/even mass bounce) — PAR-60
# ===========================================================================
# New `return_creatures_by_power_parity` effect; the "choose odd or even" is
# a `modes` choice of the two fixed-parity variants. Documented
# simplification: the leading "You may put a +1/+1 counter on a creature"
# rider (a parity nudge) is dropped — the parity mass bounce is the payoff.


def _zimones_hypothesis() -> list[AbilitySpec]:
    """You may put a +1/+1 counter on a creature. Then choose odd or even.
    Return each creature with power of the chosen quality to its owner's
    hand. (Zero is even.)"""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={"choose": 1, "options": [
                [EffectSpec("return_creatures_by_power_parity", {"parity": "odd"})],
                [EffectSpec("return_creatures_by_power_parity", {"parity": "even"})],
            ], "descriptions": ["ungerade", "gerade"]},
        ),
    ]


register("Zimone's Hypothesis", _zimones_hypothesis)

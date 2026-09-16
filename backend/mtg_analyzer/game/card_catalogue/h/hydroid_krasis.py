from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Hydroid Krasis "half X" cast payoff
# ===========================================================================


def _hydroid_krasis() -> list[AbilitySpec]:
    """When you cast this spell, you gain half X life and draw half X cards.
    Round down each time.
    Flying, trample
    This creature enters with X +1/+1 counters on it.

    Documented simplification: the "when you cast this spell" trigger is
    modeled as a resolution (`spell_effect`) payoff — it happens as the
    spell resolves rather than on cast, a minor timing difference (it can't
    be responded to between). The ``half_x_down`` sentinel is rewritten by
    `RulesEngine._substitute_x` to floor(X/2)."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"amount": "half_x_down"}),
                EffectSpec("draw", {"count": "half_x_down"}),
            ],
        ),
    ]


register("Hydroid Krasis", _hydroid_krasis)

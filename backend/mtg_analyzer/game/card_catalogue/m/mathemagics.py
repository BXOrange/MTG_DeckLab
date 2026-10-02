from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mathemagics() -> list[AbilitySpec]:
    """Target player draws 2^X cards.

    — PLAY-ALL Step 2 (Hydranten). A targeted `draw` whose ``count`` is an
    `effect_amounts` operand: the spell's own paid X (``x_paid``) run through
    the new ``power_of`` modifier (base 2, exponent clamped by
    `effect_amounts.MAX_POWER_OF_EXPONENT`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {
                "target_kind": "player",
                "count": {"kind": "x_paid", "of": "source", "power_of": 2},
            })],
        )
    ]


register("Mathemagics", _mathemagics)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dramatic_reversal() -> list[AbilitySpec]:
    """Untap all nonland permanents you control.

    — Dramatic Reversal. `TapEffect` in its untargeted mass-untap mode via
    the new ``nonland_permanents_you_control`` group selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("tap", {
                "untap": True, "selector": "nonland_permanents_you_control",
            })],
        )
    ]


register("Dramatic Reversal", _dramatic_reversal)

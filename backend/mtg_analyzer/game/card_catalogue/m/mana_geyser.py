from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_geyser() -> list[AbilitySpec]:
    """Add {R} for each tapped land your opponents control.

    — Imodane deck batch. `AddManaEffect`'s existing `amount_selector`,
    with the new unscoped-to-opponents `tapped_lands_opponents_control`
    count selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "R", "amount_selector": "tapped_lands_opponents_control"})],
        ),
    ]


register("Mana Geyser", _mana_geyser)

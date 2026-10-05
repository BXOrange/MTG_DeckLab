from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _snap() -> list[AbilitySpec]:
    """Return target creature to its owner's hand. Untap up to two lands.

    — Snap. Two independent targeting effects on one spell (RULE 115.1a) —
    the bounce and the "up to two" land untap — resolved via `StackItem.
    target_groups` (2026-07-16's generalization, previously only exercised
    for a triggered ability's own auto-gathered per-effect target; a caller
    must supply ``target_groups`` explicitly for a spell). `TapEffect`
    gained a ``count`` param this batch (RULE 115.1a's N>=2 generalization,
    mirroring `DestroyEffect.count`) for the "up to two" half.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "creature"}),
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "untap": True,
                    "optional": True, "count": 2,
                }),
            ],
        )
    ]


register("Snap", _snap)

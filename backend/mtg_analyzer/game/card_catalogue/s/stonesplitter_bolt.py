from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stonesplitter_bolt() -> list[AbilitySpec]:
    """Bargain
    Stonesplitter Bolt deals X damage to target creature or planeswalker.
    If this spell was bargained, it deals twice X damage to that
    permanent instead.

    — Imodane deck batch. Bargain comes from the RULE 702 keyword
    catalogue automatically. The damage clause is `DealDamageEffect`'s new
    `double_if_bargained`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature_or_planeswalker", "double_if_bargained": True,
            })],
        ),
    ]


register("Stonesplitter Bolt", _stonesplitter_bolt)

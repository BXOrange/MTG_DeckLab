from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirrormade() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any artifact or
    enchantment on the battlefield.

    — Mirrormade. The same `enter_as_copy` replacement mechanism Phyrexian
    Metamorph/Clever Impersonator use; ``target_kind="permanent"`` is the
    same documented "no type-union target kind" simplification those
    entries already use (admits a creature/land/planeswalker pick too,
    never correct oracle-text-wise but not currently prevented).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
        )
    ]


register("Mirrormade", _mirrormade)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _masterwork_of_ingenuity() -> list[AbilitySpec]:
    """You may have this Equipment enter as a copy of any Equipment on the
    battlefield.

    Simplified: widened to "any permanent" — the target-kind vocabulary
    (docs/11 §10) has no Equipment-only restriction, matching the same
    documented looseness `Clever Impersonator`'s own catalogue entry
    already accepts for "any nonland permanent".
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
        ),
    ]


register("Masterwork of Ingenuity", _masterwork_of_ingenuity)

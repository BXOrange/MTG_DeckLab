from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _copy_enchantment() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any enchantment on the
    battlefield.

    — Copy Enchantment. Same `enter_as_copy` mechanism as Clever Impersonator
    (see its docstring), narrowed to ``target_kind="enchantment"`` (the new
    single-type target kind).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "enchantment"})],
        )
    ]


register("Copy Enchantment", _copy_enchantment)

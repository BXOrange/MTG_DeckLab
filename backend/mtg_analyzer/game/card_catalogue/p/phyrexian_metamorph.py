from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _phyrexian_metamorph() -> list[AbilitySpec]:
    """({U/P} can be paid with either {U} or 2 life.)
    You may have this creature enter as a copy of any artifact or creature
    on the battlefield, except it's an artifact in addition to its other
    types.

    — Phyrexian Metamorph. The Phyrexian-mana reminder-text line is inert
    (parsed elsewhere, independent of this registry). Same `enter_as_copy`
    mechanism as Clever Impersonator (see its docstring); ``target_kind=
    "permanent"`` is the same "no type-union target kind" simplification
    (drops the artifact/creature restriction, permitting an enchantment/
    land/planeswalker pick too — never correct oracle-text-wise but not
    currently prevented, exactly Clever Impersonator's own documented gap).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent", "add_types": ["Artifact"]})],
        )
    ]


register("Phyrexian Metamorph", _phyrexian_metamorph)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mockingbird() -> list[AbilitySpec]:
    """Flying
    You may have this creature enter as a copy of any creature on the
    battlefield with mana value less than or equal to the amount of mana
    spent to cast this creature, except it's a Bird in addition to its
    other types and it has flying.

    — MEC-12 (cEDH staples 2). Flying is already parser-claimed for free;
    the `enter_as_copy` replacement carries the rest —
    ``max_mana_value_from_mana_spent`` reads `GameObject.mana_spent_to_cast`
    live when the choice is offered (an {X} creature spell, so the real cap
    is whatever {X} the caster chose), ``add_subtypes``/``add_keywords`` the
    "except" clause.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "max_mana_value_from_mana_spent": True,
                "add_subtypes": ["Bird"], "add_keywords": ["Flying"],
            })],
        ),
    ]


register("Mockingbird", _mockingbird)

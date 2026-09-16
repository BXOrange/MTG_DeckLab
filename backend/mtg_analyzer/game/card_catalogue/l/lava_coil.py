from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lava_coil() -> list[AbilitySpec]:
    """Lava Coil deals 4 damage to target creature. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. The second clause is the new
    `grant_die_to_exile_this_turn` — see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "creature"}),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
        ),
    ]


register("Lava Coil", _lava_coil)

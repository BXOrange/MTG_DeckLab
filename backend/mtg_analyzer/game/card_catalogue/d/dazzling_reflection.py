from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dazzling_reflection() -> list[AbilitySpec]:
    """You gain life equal to target creature's power. The next time that
    creature would deal damage this turn, prevent that damage.

    — a `bind` over the target creature's power (MEC-30) that reads the *same* target `prevent_damage_from_target`'s own
    ``target_kind="creature"`` gathers — only one real RULE 115 target
    requirement in this whole ability, so `_apply_effects_partitioned`
    hands both effects the same resolved list (RULE 608.2).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("bind", {
                    "name": "power",
                    "amount": {"kind": "characteristic", "characteristic": "power", "of": "target"},
                    "effects": [{"type": "gain_life", "params": {"amount": "$power"}}],
                }),
                EffectSpec("prevent_damage_from_target", {"target_kind": "creature", "amount": "all"}),
            ],
        ),
    ]


register("Dazzling Reflection", _dazzling_reflection)

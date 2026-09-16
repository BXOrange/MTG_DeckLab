from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _volcanic_salvo() -> list[AbilitySpec]:
    """This spell costs {X} less to cast, where X is the total power of
    creatures you control.
    Volcanic Salvo deals 6 damage to each of up to two target creatures
    and/or planeswalkers."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "per": "total_power_creatures_you_control",
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 6, "target_kind": "creature_or_planeswalker", "count": 2,
                "optional": True,
            })],
        ),
    ]


register("Volcanic Salvo", _volcanic_salvo)

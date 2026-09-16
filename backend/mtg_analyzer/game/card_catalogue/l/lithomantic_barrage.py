from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lithomantic_barrage() -> list[AbilitySpec]:
    """This spell can't be countered.
    Lithomantic Barrage deals 1 damage to target creature or planeswalker.
    It deals 5 damage instead if that target is white and/or blue.

    — Imodane deck batch. "Can't be countered" already parses on its own
    — reproduced verbatim. The damage clause is `DealDamageEffect`'s new
    `amount_if_target_color`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 1, "target_kind": "creature_or_planeswalker",
                "amount_if_target_color": {"amount": 5, "colors": ["W", "U"]},
            })],
        ),
    ]


register("Lithomantic Barrage", _lithomantic_barrage)

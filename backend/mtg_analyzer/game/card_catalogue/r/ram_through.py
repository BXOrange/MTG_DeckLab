from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ram_through() -> list[AbilitySpec]:
    """Target creature you control deals damage equal to its power to target
    creature you don't control. If the creature you control has trample,
    excess damage is dealt to that creature's controller instead.

    — PLAY-ALL Step 2 (Kodama). `damage_equal_to_power` (the one-sided
    fight, Rabid Bite) with its new ``excess_to_controller_if_trample`` flag
    (`library.DamageEqualToPowerEffect`): a trampling dealer puts only lethal
    damage on the creature and the rest on its controller.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_equal_to_power", {
                "dealer_kind": "creature_you_control", "target_kind": "creature_you_dont_control",
                "excess_to_controller_if_trample": True,
            })],
        )
    ]


register("Ram Through", _ram_through)

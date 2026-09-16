from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reverse_damage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
        ),
    ]


register("Reverse Damage", _reverse_damage)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pilgrim_of_virtue() -> list[AbilitySpec]:
    """Protection from black
    {W}, Sacrifice this creature: The next time a black source of your
    choice would deal damage this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "B"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
        ),
    ]


register("Pilgrim of Virtue", _pilgrim_of_virtue)

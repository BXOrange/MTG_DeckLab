from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cho_arrim_alchemist() -> list[AbilitySpec]:
    """{1}{W}{W}, {T}, Discard a card: The next time a source of your choice
    would deal damage to you this turn, prevent that damage. You gain life
    equal to the damage prevented this way.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            cost={"text": "{1}{W}{W}, {T}, Discard a card"},
        ),
    ]


register("Cho-Arrim Alchemist", _cho_arrim_alchemist)

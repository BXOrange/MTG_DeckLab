from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pentagram_of_the_ages() -> list[AbilitySpec]:
    """{4}, {T}: The next time a source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{4}, {T}"},
        ),
    ]


register("Pentagram of the Ages", _pentagram_of_the_ages)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _greater_realm_of_preservation() -> list[AbilitySpec]:
    """{1}{W}: The next time a black or red source of your choice would deal
    damage to you this turn, prevent that damage.

    — ``source_filter={"color_any": ["B", "R"]}`` (MEC-30's new multi-colour
    filter key, ``color``'s "any of" sibling).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
        ),
    ]


register("Greater Realm of Preservation", _greater_realm_of_preservation)

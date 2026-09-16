from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _filth() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Swamp, creatures you control have swampwalk.

    — Filth, `_anger`'s black sibling (MEC-22). ``"swampwalk"`` is a
    landwalk slug, not a FLAG keyword, but `grant_keyword`'s
    `keywords` list already accepts either shape identically
    (`combat._landwalk_slugs` matches any granted keyword ending
    "walk"), so no different EffectSpec params are needed here than
    Anger's/Brawn's.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["swampwalk"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_swamp",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Filth", _filth)

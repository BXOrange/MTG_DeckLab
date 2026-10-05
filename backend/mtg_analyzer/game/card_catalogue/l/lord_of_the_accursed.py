from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lord_of_the_accursed() -> list[AbilitySpec]:
    """Other Zombies you control get +1/+1.
    {1}{B}, {T}: All Zombies gain menace until end of turn.

    — PLAY-ALL Step 2 (Eternal Might / Wretched Ranks). The anthem is the parser's own claim. The activation is a
    group `pump` over every Zombie on the battlefield (``of: "any"`` — "all Zombies", not only yours).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 1, "affects": "other_creatures_you_control", "subtype": "Zombie",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["menace"],
                "selector": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "subtype": "zombie"}},
            })],
            cost={"mana": "{1}{B}", "taps_self": True},
        ),
    ]


register("Lord of the Accursed", _lord_of_the_accursed)

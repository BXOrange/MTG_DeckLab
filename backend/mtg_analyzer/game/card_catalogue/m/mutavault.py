from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: `continuous.ALL_CREATURE_TYPES` — the `add_subtypes` marker for "is every creature type" (RULE 702.73a).
_ALL_CREATURE_TYPES = "changeling"


def _mutavault() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}: This land becomes a 2/2 creature with all creature types until end of turn. It's still a land.

    — PLAY-ALL (Shorikai Vehicles). The mana ability is auto-bound. The animation is a self-targeted `grant_until` with a layer-4 `type_change`
    (creature added alongside land, 2/2, every creature type through the `changeling` subtype marker `PAR-109` introduced).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "add_subtypes": [_ALL_CREATURE_TYPES], "power": 2, "toughness": 2,
                }},
            })],
            cost={"mana": "{1}"},
        ),
    ]


register("Mutavault", _mutavault)

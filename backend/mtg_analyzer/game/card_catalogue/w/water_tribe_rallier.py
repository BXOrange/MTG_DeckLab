from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _water_tribe_rallier() -> list[AbilitySpec]:
    """Waterbend {5}: Look at the top four cards of your library. You may
    reveal a creature card with power 3 or less from among them and put it
    into your hand. Put the rest on the bottom of your library in a random
    order.

    — the `look_top_select` reveal-filter variant (PAR-30): ``select_
    optional`` ("you may reveal") + ``select_filter`` ({card_type: creature,
    max_power: 3}) + ``rest_order="random"``. Cost is the waterbend {5} as a
    plain {5} activated cost.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("look_top_select", {
                "count": 4,
                "select_count": 1,
                "select_optional": True,
                "select_filter": {"card_type": "creature", "max_power": 3},
                "rest_destination": "library_bottom",
                "rest_order": "random",
            })],
            cost={"mana": "{5}"},
        ),
    ]


register("Water Tribe Rallier", _water_tribe_rallier)

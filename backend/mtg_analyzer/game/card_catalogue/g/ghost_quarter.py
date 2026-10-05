from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghost_quarter() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice this land: Destroy target land. Its controller may
    search their library for a basic land card, put it onto the
    battlefield, then shuffle.

    The destroy-and-optional-search effect routes the pending library choice
    to the destroyed land's controller rather than to this ability's source
    controller.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec(
                "destroy_controller_may_search_basic_land",
                {"target_kind": "land"},
            )],
            cost={"taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Ghost Quarter", _ghost_quarter)

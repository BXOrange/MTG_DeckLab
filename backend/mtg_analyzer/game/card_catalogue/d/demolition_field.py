from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demolition_field() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {2}, {T}, Sacrifice this land: Destroy target nonbasic land an opponent controls. That land's controller may search their library for a basic land card, put it onto the battlefield, then shuffle. You may search your library for a basic land card, put it onto the battlefield, then shuffle.

    — PLAY-ALL (Scions & Spellcraft). The mana ability is auto-bound. Ghost Quarter's `destroy_controller_may_search_basic_land`
    over the ``nonbasic_land_you_dont_control`` target (the opponent's search), then your own `search`.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("destroy_controller_may_search_basic_land", {"target_kind": "nonbasic_land_you_dont_control"}),
                EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield", "count": 1, "optional": True}),
            ],
            cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Demolition Field", _demolition_field)

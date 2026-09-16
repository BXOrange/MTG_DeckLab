from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zimone_quandrix_prodigy() -> list[AbilitySpec]:
    """{1}, {T}: You may put a land card from your hand onto the battlefield
    tapped.
    {4}, {T}: Draw a card. If you control eight or more lands, draw two cards
    instead."""
    ZIMONE_LAND_THRESHOLD = 8
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": {"type": "land"}, "count": 1, "tapped": True, "optional": True,
            })],
            cost={"text": "{1}, {T}"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "condition": {
                    "count_selector_at_least": {"selector": "lands_you_control",
                                                "count": ZIMONE_LAND_THRESHOLD},
                }}),
            ],
            cost={"text": "{4}, {T}"},
        ),
    ]


register("Zimone, Quandrix Prodigy", _zimone_quandrix_prodigy)

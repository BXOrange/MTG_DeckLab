from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _riverchurn_monument() -> list[AbilitySpec]:
    """{1}, {T}: Any number of target players each mill two cards.
    Exhaust — {2}{U}{U}, {T}: Any number of target players each mill cards equal to the number of cards in their graveyard. (Activate each exhaust ability only once.)

    — PLAY-ALL (Hope to the last). Both activations announce any number
    of distinct player targets, including zero. The exhaust mill measures each
    player's own graveyard at resolution and marks the ability used once.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {"count": 2, "target_kind": "player", "any_number_of_players": True})],
            cost={"text": "{1}, {t}"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("mill", {
                    "target_kind": "player",
                    "any_number_of_players": True,
                    "count": {"kind": "resource", "resource": "graveyard_size", "of": "target"},
                }),
                EffectSpec("activate_only_once_marker", {}),
            ],
            cost={"text": "{2}{u}{u}, {t}"},
        ),
    ]


register("Riverchurn Monument", _riverchurn_monument)

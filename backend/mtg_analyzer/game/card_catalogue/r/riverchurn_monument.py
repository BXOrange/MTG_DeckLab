from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _riverchurn_monument() -> list[AbilitySpec]:
    """{1}, {T}: Any number of target players each mill two cards.
    Exhaust — {2}{U}{U}, {T}: Any number of target players each mill cards equal to the number of cards in their graveyard. (Activate each exhaust ability only once.)

    — PLAY-ALL (Hope to the last). **Simplification:** "any number of target players" is one target player (a
    `mill` ``target_kind="player"``). The exhaust ability sizes the mill by the target's own graveyard (``resource``
    ``graveyard_size`` of the ``target``) and carries `activate_only_once_marker` (RULE 702.177a, as Invasion Submersible).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {"count": 2, "target_kind": "player"})],
            cost={"text": "{1}, {t}"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("mill", {
                    "target_kind": "player",
                    "count": {"kind": "resource", "resource": "graveyard_size", "of": "target"},
                }),
                EffectSpec("activate_only_once_marker", {}),
            ],
            cost={"text": "{2}{u}{u}, {t}"},
        ),
    ]


register("Riverchurn Monument", _riverchurn_monument)

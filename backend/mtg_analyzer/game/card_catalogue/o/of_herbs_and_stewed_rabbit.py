from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _of_herbs_and_stewed_rabbit() -> list[AbilitySpec]:
    """I — Put a +1/+1 counter on up to one target creature. Create a Food
    token.
    II — Draw a card. Create a Food token.
    III — Create a 1/1 white Halfling creature token for each Food you
    control.

    Chapters I/II are carried over verbatim from what the parser already
    resolves on its own; only chapter III (a "for each Food you control"
    dynamic count no `create_token` handler recognizes yet) needed
    hand-authoring — same shape as Vault 12: The Necropolis's own chapter
    II, just with the new ``foods_you_control`` count selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"target_kind": "creature", "optional": True}),
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
            ],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                "token_name": "Halfling", "count_selector": "foods_you_control",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Of Herbs and Stewed Rabbit", _of_herbs_and_stewed_rabbit)

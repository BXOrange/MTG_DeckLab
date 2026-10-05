from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _rabbit(**extra) -> dict:
    return {"count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Rabbit"], "keywords": [],
            "token_name": "Rabbit", **extra}


def _tempt_with_bunnies() -> list[AbilitySpec]:
    """Tempting offer — Draw a card and create a 1/1 white Rabbit creature token. Then each opponent may draw a
    card and create a 1/1 white Rabbit creature token. For each opponent who does, you draw a card and you
    create a 1/1 white Rabbit creature token.

    — Peace Offering deck batch. Your own draw and token first; then `for_each` over the opponents, each asked
    (a free `pay_cost_then`, ``payer="target"``, answered Ja/Nein) whether to take the offer; the body runs as
    you with the opponent as its target — their draw and token go to the target, your bonus is the untargeted
    default. **Documented simplification:** the "for each opponent
    who does" bonus is paid out as each opponent accepts rather than after every opponent has answered — same
    totals, only the interleaving of the draws differs.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("draw", {"count": 1}),
            EffectSpec("create_token", _rabbit()),
            EffectSpec("for_each", {
                "over": {"players": "each_opponent"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Draw a card and create a 1/1 Rabbit?",
                    "effects": [
                        {"type": "draw", "params": {"count": 1, "target_kind": "player"}},
                        {"type": "create_token", "params": _rabbit(creators="target")},
                        {"type": "draw", "params": {"count": 1}},
                        {"type": "create_token", "params": _rabbit()},
                    ],
                }}],
            }),
        ]),
    ]


register("Tempt with Bunnies", _tempt_with_bunnies)

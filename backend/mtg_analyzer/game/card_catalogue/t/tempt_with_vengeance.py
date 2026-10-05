from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elementals() -> dict:
    return {"count": {"kind": "x_paid", "of": "source"}, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Elemental"],
            "keywords": ["haste"], "token_name": "Elemental"}


def _tempt_with_vengeance() -> list[AbilitySpec]:
    """Tempting offer — Create X 1/1 red Elemental creature tokens with haste. Each opponent may create X 1/1 red Elemental creature tokens with haste. For each opponent who does, create X 1/1 red Elemental creature tokens with haste.

    — Tempt with Vengeance. Tempt with Bunnies' shape: your X tokens first, then a `for_each` over the
    opponents, each asked (a free `pay_cost_then`, ``payer="target"``) whether to take the offer; an accepting
    opponent makes X of their own and you make X more. Same documented simplification as Bunnies: the bonus is
    paid out as each opponent accepts rather than after every opponent has answered — same totals.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("create_token", _elementals()),
            EffectSpec("for_each", {
                "over": {"players": "each_opponent"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Create X 1/1 Elemental tokens with haste?",
                    "effects": [
                        {"type": "create_token", "params": {**_elementals(), "creators": "target"}},
                        {"type": "create_token", "params": _elementals()},
                    ],
                }}],
            }),
        ]),
    ]


register("Tempt with Vengeance", _tempt_with_vengeance)

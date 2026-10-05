from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Every non-land card type — a revealed card that has any of them is a "nonland card" (RULE 205.2a).
_NONLAND_TYPES = ("creature", "artifact", "enchantment", "instant", "sorcery", "planeswalker", "battle")


def _selvala_explorer_returned() -> list[AbilitySpec]:
    """Parley — {T}: Each player reveals the top card of their library. For each nonland card revealed this
    way, add {G} and you gain 1 life. Then each player draws a card. (Activate only as an instant.)

    — Peace Offering deck batch. A `for_each` over every player; each item is the body's target, so `reveal_top`'s
    ``whose="target"`` reveals *that* player's top card, and the nonland branch (the body still acts as Selvala's
    controller) adds {G} and gains the life for them. The closing draw is
    `draw`'s ``each_player`` selector. Activating at instant speed is the ordinary default for a non-loyalty
    activated ability.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("for_each", {
                    "over": {"players": "each_player"},
                    "effects": [
                        {"type": "reveal_top", "params": {"whose": "target"}},
                        {"type": "if_else", "params": {
                            "condition": {"kind": "any", "conditions": [
                                {"kind": "is_card_type", "of": "revealed", "card_type": t}
                                for t in _NONLAND_TYPES
                            ]},
                            "then": [
                                {"type": "add_mana", "params": {"colors": ["G"], "color": "G"}},
                                {"type": "gain_life", "params": {"amount": 1}},
                            ],
                        }},
                    ],
                }),
                EffectSpec("draw", {"count": 1, "selector": "each_player"}),
            ],
            cost={"text": "{t}"},
        ),
    ]


register("Selvala, Explorer Returned", _selvala_explorer_returned)

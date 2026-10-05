from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jolrael_mwonvuli_recluse() -> list[AbilitySpec]:
    """Whenever you draw your second card each turn, create a 2/2 green Cat creature token.
    {4}{G}{G}: Until end of turn, creatures you control have base power and toughness X/X, where X is the number
    of cards in your hand.

    — Peace Offering deck batch. The Cat trigger is the parser's own claim. The pump is `grant_until` over a
    `pt_set` whose power/toughness are the new ``power_count``/``toughness_count`` count selectors (a live read
    of the hand size, so it tracks the hand as it changes during the turn); ``lock_group`` fixes the affected
    creatures when the ability resolves (RULE 611.2c).
    """
    hand = {"zone": "hand", "of": "you"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["G"], "subtypes": ["Cat"], "keywords": [],
                "token_name": "Cat",
            })],
            trigger={"event": EventType.DRAW, "condition": {"subject": "you"}, "is_nth_draw_this_turn": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "pt_set", "params": {
                    "power_count": hand, "toughness_count": hand, "affects": "creatures_you_control",
                }},
                "duration": "end_of_turn", "target_kind": None, "lock_group": True,
            })],
            cost={"text": "{4}{g}{g}"},
        ),
    ]


register("Jolrael, Mwonvuli Recluse", _jolrael_mwonvuli_recluse)

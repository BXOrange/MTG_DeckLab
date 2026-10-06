from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _within_range() -> list[AbilitySpec]:
    """When this enchantment enters, create two 1/1 red Warrior creature tokens.
    Whenever you attack, each opponent loses life equal to the number of creatures attacking them.

    — Within Range. One ATTACKERS_DECLARED trigger for the whole attack declaration.
    On resolution each opponent loses life equal to the creatures currently attacking them;
    attackers aimed at their planeswalkers do not count.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Warrior"],
                "token_name": "Warrior",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("for_each", {"over": {"players": "each_opponent"}, "effects": [
                {"type": "lose_life", "params": {
                    "amount": {"kind": "count_selector", "selector": "creatures_attacking_you", "of": "target"},
                    "player": {"of": "target"},
                }},
            ]})],
            trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}},
        ),
    ]


register("Within Range", _within_range)

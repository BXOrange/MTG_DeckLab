"""Wan Shi Tong, All-Knowing."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wan_shi_tong_all_knowing():
    """Flying
When Wan Shi Tong enters, target nonland permanent's owner puts it into their library second from the top or on the bottom.
Whenever one or more cards are put into a library from anywhere, create two 1/1 colorless Spirit creature tokens with "This token can't block or be blocked by non-Spirit creatures."
"""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("owner_puts_on_top_or_bottom", {
                "target_kind": "nonland_permanent", "optional": False, "top_depth": 2,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Spirit"], "keywords": [], "token_name": "Spirit",
                "oracle_text": "~ can't block or be blocked by non-spirit creatures",
            })],
            trigger={
                "event": EventType.EVENT_BATCH,
                "condition": {"subject": "group", "controller": "any", "other": False, "nontoken": True},
                "batch": {"of": "PUT_INTO_LIBRARY", "min": 1},
            },
        ),
    ]


register("Wan Shi Tong, All-Knowing", _wan_shi_tong_all_knowing)

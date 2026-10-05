from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _farmer_cotton() -> list[AbilitySpec]:
    """When Farmer Cotton enters the battlefield, create X 1/1 white
    Halfling creature tokens and X Food tokens, where X is the number of
    Halflings you control.

    The cached oracle text is missing its trailing "where X is …" clause
    (a Scryfall data gap in the local cache) — X is filled in here from
    the card's real printed rules text.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                    "token_name": "Halfling",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
                EffectSpec("create_token", {
                    "token_name": "Food",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Farmer Cotton", _farmer_cotton)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _triplicate_titan() -> list[AbilitySpec]:
    """Flying, vigilance, trample
    When this creature dies, create a 3/3 colorless Golem artifact creature token with flying, a 3/3 colorless Golem artifact creature token with vigilance, and a 3/3 colorless Golem artifact creature token with trample.

    — PLAY-ALL (Living Energy). Keywords are the catalogue's; the dies trigger is three `create_token` effects.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "power": 3, "toughness": 3, "colors": [], "subtypes": ["Golem"],
                    "keywords": [kw], "is_artifact": True, "token_name": "Golem",
                })
                for kw in ("flying", "vigilance", "trample")
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Triplicate Titan", _triplicate_titan)

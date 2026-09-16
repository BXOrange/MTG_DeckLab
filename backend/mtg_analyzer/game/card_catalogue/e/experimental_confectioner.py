from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _experimental_confectioner() -> list[AbilitySpec]:
    """When this creature enters, create a Food token.
    Whenever you sacrifice a Food, create a 1/1 black Rat creature token
    with "This token can't block."

    Simplified: the created Rat token doesn't carry its own "can't block"
    text — `create_token`'s params have no combat-restriction hook for a
    token being created this same breath (every other combat-restriction
    consumer targets an *existing* permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["B"],
                "subtypes": ["Rat"], "token_name": "Rat",
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
        ),
    ]


register("Experimental Confectioner", _experimental_confectioner)

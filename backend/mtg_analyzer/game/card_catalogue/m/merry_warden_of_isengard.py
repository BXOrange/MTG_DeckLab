from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _merry_warden_of_isengard() -> list[AbilitySpec]:
    """Partner with Pippin, Warden of Isengard.
    Whenever one or more artifacts you control enter, create a 1/1 white
    Soldier creature token with lifelink. This ability triggers only once
    each turn.

    ("Partner with" is bound by the RULE 702 keyword catalogue directly
    off Scryfall's own keyword array — no hand-authoring needed for it.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Soldier"], "keywords": ["lifelink"], "token_name": "Soldier",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "artifact",
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
        ),
    ]


register("Merry, Warden of Isengard", _merry_warden_of_isengard)

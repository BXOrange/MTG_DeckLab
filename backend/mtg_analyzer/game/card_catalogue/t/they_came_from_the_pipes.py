from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _they_came_from_the_pipes() -> list[AbilitySpec]:
    """When this enchantment enters, manifest dread twice. (To manifest dread, look at the top two cards of your library. Put one onto the battlefield face down as a 2/2 creature and the other into your graveyard. Turn it face up any time for its mana cost if it's a creature card.)
    Whenever a face-down creature you control enters, draw a card.

    — PLAY-ALL (Jump Scare!). The draw trigger is the parser's face-down group filter. The enters trigger is two
    `manifest_dread` instructions in a row; the second resumes after the first look-at-two choice (the suspended
    remainder of the resolution). Both manifested creatures then draw (face-down creatures entering).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("manifest_dread", {}), EffectSpec("manifest_dread", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False,
                "filter": {"face_down": True, "card_type": "creature"},
            }},
        ),
    ]


register("They Came from the Pipes", _they_came_from_the_pipes)

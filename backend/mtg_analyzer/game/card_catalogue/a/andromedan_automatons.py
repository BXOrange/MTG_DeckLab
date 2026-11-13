from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: The shared search sentinel for "any number of" (see Goblin Recruiter, Bilbo).
ANY_NUMBER_OF_CARDS = 99


def _andromedan_automatons() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for any number of cards named Andromedan Automatons, reveal them, put them into your hand, then shuffle.

    RULE 701.23: an optional search for cards sharing the printed name
    (RULE 201.2); "any number" is the engine's generous fixed cap.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"name": "Andromedan Automatons"}, "destination": "hand",
                "count": ANY_NUMBER_OF_CARDS, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Andromedan Automatons", _andromedan_automatons)

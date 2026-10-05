from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _clifftop_lookout() -> list[AbilitySpec]:
    """Reach
    When this creature enters, reveal cards from the top of your library until you reveal a land
    card. Put that card onto the battlefield tapped and the rest on the bottom of your library in a
    random order.

    — Tramplesaurus Rex deck batch. Reach is a keyword. The ETB is `dig_until` for a land with the
    new ``battlefield_tapped`` hit destination (the hit enters tapped) and the rest to the bottom in
    a random order.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Land"}, "hit_destination": "battlefield_tapped",
                "rest_destination": "library_bottom_random",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Clifftop Lookout", _clifftop_lookout)

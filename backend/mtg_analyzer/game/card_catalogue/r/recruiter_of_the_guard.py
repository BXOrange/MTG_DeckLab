from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _recruiter_of_the_guard() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    toughness 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — same gap and same fix as Imperial Recruiter above,
    on `card_query.max_toughness` instead of `max_power`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_toughness": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Recruiter of the Guard", _recruiter_of_the_guard)

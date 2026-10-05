from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _imperial_recruiter() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    power 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — the generalized tutor grammar (`SearchLibraryEffect`/
    `models.cards.card_query`) doesn't parse a power/toughness qualifier after the
    search noun phrase (a documented gap on the parser side, same family as
    the already-unclaimed "with mana value X or less"); hand-authored
    directly onto the new `card_query.max_power` criteria key instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_power": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Imperial Recruiter", _imperial_recruiter)

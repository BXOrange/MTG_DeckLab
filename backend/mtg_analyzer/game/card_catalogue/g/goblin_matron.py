from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goblin_matron() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for a Goblin
    card, reveal that card, put it into your hand, then shuffle.

    — Goblin Matron. The subtype search is the same `criteria.type` shape
    Goblin Recruiter uses; "you may" is the trigger's `optional` flag, as on
    Relic Seeker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Goblin"}, "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        )
    ]


register("Goblin Matron", _goblin_matron)

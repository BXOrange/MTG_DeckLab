from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goblin_recruiter() -> list[AbilitySpec]:
    """When this creature enters, search your library for any number of
    Goblin cards, reveal them, then shuffle and put those cards on top in
    any order.

    — Goblin Recruiter. The generic search grammar's "up to N" choice loop
    already lets a player decline at any point, and `RulesEngine._finish_
    search` already shuffles first and then places each chosen card at the
    library's top one at a time (the *last* one chosen ends up on top —
    full order control, just reversed-order picking, matching "in any
    order"). "Any number" is modeled as a generous fixed cap (99, far above
    any real deck's Goblin count) rather than a genuinely open-ended count —
    the same "big enough constant" idiom no real deck can actually reach
    the edge of.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Goblin"}, "destination": "library_top", "count": 99,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Goblin Recruiter", _goblin_recruiter)

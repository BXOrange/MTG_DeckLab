from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stalwart_speartail() -> list[AbilitySpec]:
    """Enrage — Whenever Stalwart Speartail is dealt damage, other
    Dinosaurs you control and Dinosaur cards in your hand and library
    perpetually get +1/+1.
    Whenever Stalwart Speartail attacks, Stalwart Speartail deals 1 damage
    to each creature and each planeswalker.

    Simplified: only the second (attacks-trigger) ability is modeled. The
    first is RULE 121's *perpetual* effect shape (a one-time, permanent
    grant that outlives its source and reaches into hand/library, unlike
    an ordinary "as long as ~ is on the battlefield" static) — genuinely
    unsupported by this engine (`GrantUntilEffect`'s duration vocabulary,
    `game/durations.py`, is turn/game-window-scoped, not "forever,
    independent of the source"), so it's left out rather than
    approximated as an always-on static, which would be a meaningfully
    different, strictly *more* powerful card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_planeswalker"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Stalwart Speartail", _stalwart_speartail)

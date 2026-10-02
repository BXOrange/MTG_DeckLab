from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wirewood_herald() -> list[AbilitySpec]:
    """When this creature dies, you may search your library for an Elf card,
    reveal that card, put it into your hand, then shuffle.

    — PLAY-ALL Step 2 (Raggadragga). Goblin Matron's subtype-search shape
    (`criteria.type`, ``optional`` for the "you may") on a DIES trigger
    instead of ETB.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Elf"}, "destination": "hand"})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
        )
    ]


register("Wirewood Herald", _wirewood_herald)

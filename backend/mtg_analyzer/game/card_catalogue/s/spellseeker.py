from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spellseeker() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an
    instant or sorcery card with mana value 2 or less, reveal it, put it
    into your hand, then shuffle.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": ["Instant", "Sorcery"], "max_mana_value": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Spellseeker", _spellseeker)

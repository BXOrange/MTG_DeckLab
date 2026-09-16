from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smothering_abomination() -> list[AbilitySpec]:
    """Devoid
    Flying
    At the beginning of your upkeep, sacrifice a creature.
    Whenever you sacrifice a creature, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"what": "creature", "count": 1})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SACRIFICE, "condition": {"subject": "you"},
                     "sacrifice_type": "creature"},
        ),
    ]


register("Smothering Abomination", _smothering_abomination)

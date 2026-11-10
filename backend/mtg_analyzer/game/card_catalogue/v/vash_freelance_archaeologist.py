from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vash_freelance_archaeologist() -> list[AbilitySpec]:
    """At the beginning of your upkeep, surveil 1. (Look at the top card of your library. You may put it into your graveyard.)
    Whenever a card leaves your graveyard, draw a card. This ability triggers only once each turn.

    RULE 603.2 / 603.2g: ``CARD_LEFT_GRAVEYARD`` fires once per card;
    ``limit`` is the "only once each turn" cap on the ability.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 1})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.CARD_LEFT_GRAVEYARD, "graveyard_owner": "you", "limit": True},
        ),
    ]


register("Vash, Freelance Archaeologist", _vash_freelance_archaeologist)

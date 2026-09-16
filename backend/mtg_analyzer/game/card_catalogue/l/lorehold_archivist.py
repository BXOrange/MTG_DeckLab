from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lorehold_archivist() -> list[AbilitySpec]:
    """First strike
    At the beginning of your upkeep, if there are three or more artifact
    and/or creature cards in your graveyard, this creature becomes
    prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "graveyard_card_type_count_at_least",
                              "types": ["artifact", "creature"], "amount": 3},
            },
        ),
    ]


register("Lorehold Archivist", _lorehold_archivist)
register("Lorehold Archivist // Restore Relic", _lorehold_archivist)

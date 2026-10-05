from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _inspired_skypainter() -> list[AbilitySpec]:
    """Flying
    When this creature enters and whenever one or more creature tokens you
    control deal combat damage to a player, this creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
                "filter": {"is_token": True},
            },
        ),
    ]


register("Inspired Skypainter", _inspired_skypainter)
register("Inspired Skypainter // Maestro's Gift", _inspired_skypainter)

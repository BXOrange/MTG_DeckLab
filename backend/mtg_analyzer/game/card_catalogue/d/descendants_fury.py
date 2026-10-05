from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _descendants_fury() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("descendants_fury_sacrifice", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
            },
        ),
    ]


register("Descendants' Fury", _descendants_fury)

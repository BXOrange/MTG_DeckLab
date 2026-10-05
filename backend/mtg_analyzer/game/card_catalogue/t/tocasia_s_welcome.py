from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tocasias_welcome() -> list[AbilitySpec]:
    """Whenever one or more creatures you control with mana value 3 or less
    enter, draw a card. This ability triggers only once each turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you",
                              "other": False},
                "entering_mana_value_at_most": 3,
                "limit": True,
            },
        ),
    ]


register("Tocasia's Welcome", _tocasias_welcome)

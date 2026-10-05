from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _slithermuse() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered", [EffectSpec("slithermuse", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Slithermuse", _slithermuse)

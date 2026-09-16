from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _impulsivity() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered", [EffectSpec("cast_graveyard_instant_sorcery_free_exile", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Impulsivity", _impulsivity)

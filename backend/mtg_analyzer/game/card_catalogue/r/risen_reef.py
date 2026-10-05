from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _risen_reef() -> list[AbilitySpec]:
    return [AbilitySpec(
        "triggered", [EffectSpec("peek_top_land_or_hand", {})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
            "subject_subtype": "Elemental", "controller": "you",
        }},
    )]


register("Risen Reef", _risen_reef)

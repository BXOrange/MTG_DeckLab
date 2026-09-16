from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mass_of_mysteries() -> list[AbilitySpec]:
    """Combat trigger granting myriad to another controlled Elemental."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "keywords": ["myriad"],
                "target_kind": "other_creature_you_control",
                "creature_filter": {"subtype": "elemental"},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
        ),
    ]


register("Mass of Mysteries", _mass_of_mysteries)

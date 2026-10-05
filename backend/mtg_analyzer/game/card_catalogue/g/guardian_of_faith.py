from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _guardian_of_faith() -> list[AbilitySpec]:
    """Flash
    Vigilance
    When this creature enters, any number of other target creatures you
    control phase out."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("phase_out", {
                "target_kind": "other_creature_you_control", "count": 10, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Guardian of Faith", _guardian_of_faith)

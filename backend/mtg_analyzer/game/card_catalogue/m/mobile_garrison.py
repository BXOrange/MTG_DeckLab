from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mobile_garrison() -> list[AbilitySpec]:
    """Whenever this Vehicle attacks, untap another target artifact or creature you control.
    Crew 2 (Tap any number of creatures you control with total power 2 or more: This Vehicle becomes an artifact creature until end of turn.)

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword; the attack trigger is the parser's "untap target creature you control" shape widened to
    the ``artifact_or_creature_you_control`` target kind (which excludes the Vehicle itself — "another").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "artifact_or_creature_you_control", "untap": True})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Mobile Garrison", _mobile_garrison)

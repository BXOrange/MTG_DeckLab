from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vernal_sovereign() -> list[AbilitySpec]:
    """Whenever this creature enters or attacks, create a green and white
    Elemental creature token with "This token's power and toughness are each
    equal to the number of creatures you control."""
    effects = [EffectSpec("create_token", {
        "count": 1, "power": 0, "toughness": 0, "colors": ["G", "W"],
        "subtypes": ["Elemental"],
        # This is the token's own characteristic-defining ability, not a
        # one-time value captured while it is being created.  Giving the
        # token a self anthem therefore includes the token itself and keeps
        # changing as its controller's creature count changes.
        "grant_self_anthem": {
            "power": 1, "toughness": 1,
            "power_count": "creatures_you_control",
            "toughness_count": "creatures_you_control",
        },
    })]
    return [
        AbilitySpec(
            "triggered", effects,
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", effects,
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Vernal Sovereign", _vernal_sovereign)

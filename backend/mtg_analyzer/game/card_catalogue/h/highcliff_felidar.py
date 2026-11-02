from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _highcliff_felidar() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, for each opponent, choose a creature with the greatest power among creatures that player controls. Destroy those creatures.

    — Commander Cube singleton batch. Vigilance is the keyword catalogue's own ability. The ETB is a self-enters trigger
    whose body is `destroy_greatest_power_per_opponent` (`game/effects/greatest_power_destroy.py`, RULE 701.8).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy_greatest_power_per_opponent", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Highcliff Felidar", _highcliff_felidar)

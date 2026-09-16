from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mazirek_kraul_death_priest() -> list[AbilitySpec]:
    """Flying
    Whenever a player sacrifices another permanent, put a +1/+1 counter on
    each creature you control."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"selector": "each_creature_you_control"})],
            trigger={"event": EventType.SACRIFICE, "condition": {"other": True}},
        ),
    ]


register("Mazirek, Kraul Death Priest", _mazirek_kraul_death_priest)

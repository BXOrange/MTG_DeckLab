from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jadar_ghoulcaller_of_nephalia() -> list[AbilitySpec]:
    """At the beginning of your end step, if you control no creatures with
    decayed, create a 2/2 black Zombie creature token with decayed."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Zombie", "power": 2, "toughness": 2,
                "colors": ["B"], "subtypes": ["Zombie"], "keywords": ["decayed"],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "control_no_creatures_with_keyword", "keyword": "decayed"},
            },
        ),
    ]


register("Jadar, Ghoulcaller of Nephalia", _jadar_ghoulcaller_of_nephalia)

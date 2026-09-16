from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mycoloth() -> list[AbilitySpec]:
    """Devour 2
    At the beginning of your upkeep, create a 1/1 green Saproling creature
    token for each +1/+1 counter on this creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Saproling", "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Saproling"], "count_selector": "plus_one_counters_on_source",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
        ),
    ]


register("Mycoloth", _mycoloth)

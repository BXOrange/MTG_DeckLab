from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ribtruss_roaster() -> list[AbilitySpec]:
    """Devour 1
    At the beginning of your end step, create a number of 1/1 black and green
    Pest creature tokens equal to the number of +1/+1 counters on this
    creature. They have "When this token dies, you gain 1 life."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Pest", "power": 1, "toughness": 1, "colors": ["B", "G"],
                "subtypes": ["Pest"], "count_selector": "plus_one_counters_on_source",
                "token_dies_gain_life": 1,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Ribtruss Roaster", _ribtruss_roaster)

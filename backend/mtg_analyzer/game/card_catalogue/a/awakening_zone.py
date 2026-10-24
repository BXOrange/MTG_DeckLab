from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Witherbloom Pestilence: Eldrazi Spawn / devour token payoffs,
# recursion, and the sacrifice tail. Engine: ``plus_one_counters_on_source``
# `continuous.count_selector`; ``opponent_life_at_most`` `static_conditions`
# kind.
# ===========================================================================
#


def _awakening_zone() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may create a 0/1 colorless
    Eldrazi Spawn creature token. It has "Sacrifice this token: Add {C}."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Eldrazi Spawn", "power": 0, "toughness": 1,
                "colors": [], "subtypes": ["Eldrazi", "Spawn"],
                "oracle_text": "Sacrifice this token: Add {C}.",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Awakening Zone", _awakening_zone)

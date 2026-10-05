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
# Documented simplification shared by Awakening Zone / Pawn of Ulamog: the
# 0/1 Eldrazi Spawn token is created as a plain colourless body — its own
# "Sacrifice this creature: Add {C}" mana ability is not baked on (no
# `create_token` param grants a token a quoted activated ability yet).


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
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Awakening Zone", _awakening_zone)

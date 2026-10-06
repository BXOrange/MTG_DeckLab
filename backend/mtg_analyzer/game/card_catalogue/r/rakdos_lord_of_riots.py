from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rakdos_lord_of_riots() -> list[AbilitySpec]:
    """You can't cast Rakdos unless an opponent lost life this turn.
    Flying, trample
    Creature spells you cast cost {1} less to cast for each 1 life your opponents have lost this turn.

    — PLAY-ALL (Endless Punishment). Flying/trample are keywords. The cast restriction is a ``cast_condition`` with the new ``opponent_lost_life_this_turn`` key
    (RULE 119.3, event-derived). The discount is Chandra's Incinerator's per-count `cost_reduction` over the new ``opponents_life_lost_this_turn`` selector,
    restricted to your creature spells.
    """
    return [
        AbilitySpec("spell_effect", [], cast_condition={"opponent_lost_life_this_turn": True}),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 1, "spell_type": "creature", "per": "opponents_life_lost_this_turn",
            })],
        ),
    ]


register("Rakdos, Lord of Riots", _rakdos_lord_of_riots)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Priest of Forgotten Gods (pure composition of shipped primitives)
# ===========================================================================


def _priest_of_forgotten_gods() -> list[AbilitySpec]:
    """{T}, Sacrifice two other creatures: Any number of target players each
    lose 2 life and sacrifice a creature of their choice. You add {B}{B} and
    draw a card.

    Documented simplification: "any number of target players" is modeled as
    "each opponent" (the standard goldfish reading — `LoseLifeEffect` /
    `SacrificeEffect` both already take ``selector="each_opponent"``)."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}),
             EffectSpec("sacrifice", {"selector": "each_opponent", "what": "creature",
                                      "count": 1}),
             EffectSpec("add_mana", {"colors": ["B", "B"]}),
             EffectSpec("draw", {"count": 1})],
            cost={"text": "{T}", "sacrifice_count": [2, "creature"]},
        ),
    ]


register("Priest of Forgotten Gods", _priest_of_forgotten_gods)

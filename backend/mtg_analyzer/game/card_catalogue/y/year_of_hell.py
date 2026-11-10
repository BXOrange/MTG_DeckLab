from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _year_of_hell() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I, II, III — Each player draws a card. This Saga deals 2 damage to each player.

    RULE 714.2: the Saga's chapter trigger fires on lore-counter additions;
    both halves of the chapter resolve in order on one stack object.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1, "selector": "each_player"}),
                EffectSpec("damage", {"amount": 2, "selector": "each_player"}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1, 2, 3]},
        ),
    ]


register("Year of Hell", _year_of_hell)

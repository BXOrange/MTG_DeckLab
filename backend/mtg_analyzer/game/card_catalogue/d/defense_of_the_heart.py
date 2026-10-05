from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _defense_of_the_heart() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if an opponent controls three or
    more creatures, sacrifice this enchantment, search your library for up
    to two creature cards, put those cards onto the battlefield, then
    shuffle.

    — MEC-43. A RULE 500.7 upkeep trigger gated by the new ``min_opponent_
    creatures`` RULE 603.4 intervening-if (`effect_binder._trigger_
    condition`), whose effects are a plain `sacrifice_self` followed by
    `SearchLibraryEffect(count=2, destination="battlefield")` — "up to two"
    is that effect's own existing ``optional=True`` default.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice_self", {}),
                EffectSpec("search", {
                    "criteria": {"type": "Creature"}, "count": 2, "destination": "battlefield",
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "min_opponent_creatures": 3,
            },
        ),
    ]


register("Defense of the Heart", _defense_of_the_heart)

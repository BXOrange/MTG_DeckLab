from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Breena, the Demagogue (multi-opponent life-compare trigger) —
# PAR-60
# ===========================================================================
# `defending_opponent_leads_an_opponent` binder intervening-if predicate
# ("that opponent has more life than another of your opponents") + a
# `selector="attacking_player"` mode on `DrawCardEffect` (draw for the
# `PLAYER_ATTACKED` aggregate's named attacker, not this controller).


def _breena_the_demagogue() -> list[AbilitySpec]:
    """Flying (folds in).
    Whenever a player attacks one of your opponents, if that opponent has
    more life than another of your opponents, that attacking player draws a
    card and you put two +1/+1 counters on a creature you control."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1, "selector": "attacking_player"}),
                EffectSpec("add_counters", {
                    "count": 2, "kind": "+1/+1", "target_kind": "creature_you_control",
                }),
            ],
            trigger={"event": EventType.PLAYER_ATTACKED, "defender_is_opponent": True,
                     "defending_opponent_leads_an_opponent": True},
        ),
    ]


register("Breena, the Demagogue", _breena_the_demagogue)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_eldest_reborn() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Each opponent sacrifices a creature or planeswalker of their choice.
    II — Each opponent discards a card.
    III — Put target creature or planeswalker card from a graveyard onto the battlefield under your control.

    — PLAY-ALL (Miracle Worker). Chapter I is Professor Onyx's `sacrifice` edict over ``creature_or_planeswalker`` for each opponent; II is the
    parser's `discard`; III is `return_from_graveyard` over the any-graveyard ``creature_or_planeswalker`` kind under your control.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"what": "creature_or_planeswalker", "count": 1, "selector": "each_opponent"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("discard", {"count": 1, "scope": "each_opponent"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_creature_or_planeswalker", "destination": "battlefield",
                "under_your_control": True,
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("The Eldest Reborn", _the_eldest_reborn)

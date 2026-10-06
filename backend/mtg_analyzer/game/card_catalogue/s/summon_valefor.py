from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_valefor() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)
    I — Sonic Wings — Each opponent chooses a creature with the greatest mana value among creatures they control. Return those creatures to their owners' hands.
    II, III, IV — Tap up to one target creature and put a stun counter on it.
    Flying

    — PLAY-ALL (Counter Blitz). Flying is the keyword. Chapter I is the new `each_opponent_returns_greatest_mv_creature` (ties broken in the opponent's favour).
    Chapters II–IV are Fear of Sleep Paralysis' optional `tap` plus a stun `add_counters` on the same creature (``previous_subject``).
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("each_opponent_returns_greatest_mv_creature", {})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "creature", "optional": True}),
                EffectSpec("add_counters", {"kind": "stun", "amount": 1, "previous_subject": True}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2, 3, 4]},
        ),
    ]


register("Summon: Valefor", _summon_valefor)

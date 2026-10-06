from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_ixion() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Aerospark — Exile target creature an opponent controls until this Saga leaves the battlefield.
    II, III — Put a +1/+1 counter on each of up to two target creatures you control. You gain 2 life.
    First strike

    — PLAY-ALL (Counter Blitz). First strike is the keyword. Chapter I is Portable Hole's linked exile (``remember`` + `return_linked_exile` when the Saga
    leaves; the return is respondable). Chapters II and III are `add_counters` over up to two creatures you control (``target_count`` 2) and `gain_life`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {
                    "count": 1, "kind": "+1/+1", "target_kind": "creature_you_control", "target_count": 2, "optional": True,
                }),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2, 3]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Summon: Ixion", _summon_ixion)

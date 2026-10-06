from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fear_of_sleep_paralysis() -> list[AbilitySpec]:
    """Flying
    Eerie — Whenever this creature or another enchantment you control enters and whenever you fully unlock a Room, tap up to one target creature and put a stun counter on it.
    Stun counters can't be removed from permanents your opponents control. (They won't untap if they have stun counters.)

    — PLAY-ALL (Miracle Worker). Flying is the keyword's. Two enters triggers (itself, and the parser's "another enchantment you
    control") over `tap` + a stun `add_counters`. **Simplification:** Rooms have no door state, so "fully unlock a Room" never happens.
    The lock is the new ``stun_counters_cant_be_removed`` static (`continuous.stun_counters_locked`), read where an untap would spend a stun counter.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "creature", "optional": True}),
                EffectSpec("add_counters", {"kind": "stun", "amount": 1, "previous_subject": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "creature", "optional": True}),
                EffectSpec("add_counters", {"kind": "stun", "amount": 1, "previous_subject": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": True, "type": "enchantment",
            }},
        ),
        AbilitySpec("static", [EffectSpec("stun_counters_cant_be_removed", {})]),
    ]


register("Fear of Sleep Paralysis", _fear_of_sleep_paralysis)

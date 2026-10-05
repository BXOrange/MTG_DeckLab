from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _simic_ascendancy() -> list[AbilitySpec]:
    """{1}{G}{U}: Put a +1/+1 counter on target creature you control.
    Whenever one or more +1/+1 counters are put on a creature you control,
    put that many growth counters on this enchantment.
    At the beginning of your upkeep, if this enchantment has twenty or more
    growth counters on it, you win the game.

    — PLAY-ALL Step 2 (Hydranten). The activated ability is the parser's own
    claim, reproduced verbatim. The growth trigger is the parser's PAR-138
    "counters are put on a creature you control" head (`COUNTER`, group
    ``controller: you``, ``kind: +1/+1``) with the amount read off the firing
    event (``trigger_event`` / ``amount`` — the counters just placed, "that
    many"). The win is the parser's own shape for "20 or more growth counters"
    (``win_game`` with a `source_counters` condition); only the spelled-out
    "twenty" kept the card unclaimed.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_you_control"})],
            cost={"text": "{1}{G}{U}"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": {"kind": "trigger_event", "field": "amount"}, "kind": "growth",
            })],
            trigger={
                "event": EventType.COUNTER,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"card_type": "creature"},
                },
                "filter": {"kind": "+1/+1"},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("win_game", {}, condition={"kind": "source_counters", "counter": "growth", "min": 20})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Simic Ascendancy", _simic_ascendancy)

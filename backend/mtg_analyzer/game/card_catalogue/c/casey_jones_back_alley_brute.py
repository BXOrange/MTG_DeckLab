from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _casey_jones_back_alley_brute() -> list[AbilitySpec]:
    """Menace
    Whenever Casey Jones attacks, put a +1/+1 counter on target attacking creature.
    Whenever you put one or more +1/+1 counters on a creature you control, Casey Jones deals that much damage to target opponent.

    — PLAY-ALL (Turtle Power!). Menace is the keyword; the attack trigger is the parser's claim. The damage trigger is the `COUNTER` group head (a creature you control, a +1/+1 counter) over `damage` with
    ``amount_from_trigger_event`` ("amount") aimed at a target opponent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "target_kind": "creature", "creature_filter": {"attacking": True},
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"target_kind": "opponent", "amount_from_trigger_event": "amount"})],
            trigger={
                "event": EventType.COUNTER,
                "condition": {"subject": "group", "controller": "you", "other": False},
                "filter": {"kind": "+1/+1", "recipient_is_creature": True},
            },
        ),
    ]


register("Casey Jones, Back Alley Brute", _casey_jones_back_alley_brute)

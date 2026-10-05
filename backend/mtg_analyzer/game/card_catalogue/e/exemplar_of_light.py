from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _exemplar_of_light() -> list[AbilitySpec]:
    """Flying
    Whenever you gain life, put a +1/+1 counter on this creature.
    Whenever you put one or more +1/+1 counters on this creature, draw a card. This ability triggers only once each turn.

    — PLAY-ALL (Calling All Angels). The life-gain trigger is the parser's. The draw is a self-scoped `COUNTER` trigger
    filtered to +1/+1 (Mazemind Tome's shape) with ``limit`` (once each turn, as Tataru Taru's).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.COUNTER, "filter": {"kind": "+1/+1"}, "condition": {"subject": "self"},
                "limit": True,
            },
        ),
    ]


register("Exemplar of Light", _exemplar_of_light)

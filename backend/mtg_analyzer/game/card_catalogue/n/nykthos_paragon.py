from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nykthos_paragon() -> list[AbilitySpec]:
    """Whenever you gain life, you may put that many +1/+1 counters on each creature you control. Do this only once each turn.

    — PLAY-ALL (Hope to the last). An optional life-gain trigger with the once-per-turn ``limit``; a `bind` measures the
    event's ``amount`` and hands it to a group `add_counters` over ``each_creature_you_control``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "trigger_event", "field": "amount"},
                "effects": [{"type": "add_counters", "params": {
                    "amount": "$n", "kind": "+1/+1", "selector": "each_creature_you_control",
                }}],
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}, "limit": True},
            optional=True,
        ),
    ]


register("Nykthos Paragon", _nykthos_paragon)

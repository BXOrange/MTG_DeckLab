from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kianne_corrupted_memory() -> list[AbilitySpec]:
    """As long as Kianne's power is even, you may cast noncreature spells as though they had flash.
    As long as Kianne's power is odd, you may cast creature spells as though they had flash.
    Whenever you draw a card, put a +1/+1 counter on Kianne.

    — PLAY-ALL (Jump Scare!). The draw trigger is the parser's. The two permissions are `flash_permission` statics scoped
    to noncreature / creature spells and gated by the new ``parity`` bound on the `power` condition (derived power).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.DRAW, "condition": {"subject": "you"}},
        ),
        AbilitySpec("static", [EffectSpec("flash_permission", {
            "noncreature_only": True, "active_if": {"kind": "power", "parity": "even"},
        })]),
        AbilitySpec("static", [EffectSpec("flash_permission", {
            "creature_only": True, "active_if": {"kind": "power", "parity": "odd"},
        })]),
    ]


register("Kianne, Corrupted Memory", _kianne_corrupted_memory)

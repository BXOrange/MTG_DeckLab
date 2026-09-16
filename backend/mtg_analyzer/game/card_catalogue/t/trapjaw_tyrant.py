from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _trapjaw_tyrant() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, exile target
    creature an opponent controls until this creature leaves the
    battlefield.

    The O-Ring-shaped linked-exile pair (`ExileEffect(remember=True)` +
    `ReturnLinkedExileEffect` on the leaves-battlefield trigger, exactly
    `Leonin Relic-Warder`'s pattern) — the modern one-sentence "exile …
    until ~ leaves the battlefield" templating is the same RULE 610.3-style
    linked duration as Leonin's older two-sentence phrasing, just terser.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Trapjaw Tyrant", _trapjaw_tyrant)

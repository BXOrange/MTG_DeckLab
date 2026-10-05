from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arcane_denial() -> list[AbilitySpec]:
    """Counter target spell. Its controller may draw up to two cards at
    the beginning of the next turn's upkeep.
    You draw a card at the beginning of the next turn's upkeep.

    — Arcane Denial. The second sentence is exactly what the oracle-text
    parser already claims on its own (`author_card.py reuse`) — a plain
    "you draw a card next upkeep" `create_delayed_trigger`, pasted as-is.
    Only the first sentence needed a hand-written spec: the delayed draw
    belongs to the *countered spell's controller*, not this ability's own
    caster — `effects.CreateDelayedTriggerEffect`'s new
    ``capture="target_controller"`` (built for this card), which both
    arms the delayed trigger for *that* player's next upkeep and hands
    the drawn cards to them, reading the countered spell's own
    `GameObject.controller_id` at resolution (the countered spell is long
    gone by the time the delayed half actually fires).

    Documented simplification: "may draw **up to** two" is modeled as an
    unconditional draw of 2 — declining is a real but exceedingly rare
    choice (avoiding a self-mill/deck-out effect), and a delayed trigger
    has no interactive pending_choice machinery to offer it yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    # "**the** next turn's upkeep" — the very next one,
                    # whoever's turn that turns out to be, not specifically
                    # the countered spell's controller's own next turn
                    # (same reading the parser already gave the second
                    # sentence's identical phrasing, `scope: "any"` below).
                    "scope": "any",
                    "capture": "target_controller",
                    "effects": [{"type": "draw", "params": {"count": 2}}],
                    "description": "Arcane Denial: 2 Karten ziehen",
                }),
            ],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_delayed_trigger", {
                "step": "upkeep",
                "scope": "any",
                "effects": [{"type": "draw", "params": {"count": 1}}],
                "description": "Arcane Denial: 1 Karte ziehen",
            })],
        ),
    ]


register("Arcane Denial", _arcane_denial)

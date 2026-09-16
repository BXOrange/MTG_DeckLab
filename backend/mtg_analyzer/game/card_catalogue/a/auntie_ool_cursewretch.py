from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _auntie_ool_cursewretch() -> list[AbilitySpec]:
    """Ward—Blight 2. (To blight 2, a player puts two -1/-1 counters on a
    creature they control.)
    Whenever one or more -1/-1 counters are put on a creature, draw a card
    if you control that creature. If you don't control it, its controller
    loses 1 life.

    Ward—Blight 2 folds in from the RULE 702 keyword catalogue for free
    (`parse_keywords` → ``{"name": "ward", "cost": "Blight 2"}``, and
    `game/costs.parse_activation_cost` already reads "Blight 2" → RULE
    701.68). Only the trigger needs authoring: the Flourishing Defenses
    `EventType.COUNTER` shape (unscoped — any creature, any causer) with a
    two-way `ConditionalEffect` branch on the firing event's
    ``recipient_controller_id`` (`counter_recipient_is_you`): draw if it's
    yours, else that creature's controller loses 1 life
    (`LoseLifeEffect` ``selector="counter_recipient_controller"``).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}, condition={"counter_recipient_is_you": True}),
                EffectSpec(
                    "lose_life",
                    {"amount": 1, "selector": "counter_recipient_controller"},
                    condition={"counter_recipient_is_you": False},
                ),
            ],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
        ),
    ]


register("Auntie Ool, Cursewretch", _auntie_ool_cursewretch)

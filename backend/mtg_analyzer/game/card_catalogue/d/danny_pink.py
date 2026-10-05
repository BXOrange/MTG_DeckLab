from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _danny_pink() -> list[AbilitySpec]:
    """Creatures you control have "Whenever one or more counters are put
    on this creature for the first time each turn, draw a card."

    — Danny Pink. `grant_triggered_ability` (layer 6, the same quoted-
    ability-grant mechanism the hand-authored Dionus, Elvish Archdruid
    uses for its own per-creature "once each turn" grant): each creature
    you control gets its own `TriggeredAbility` watching its own
    `EventType.COUNTER` firing, capped by ``once_per_turn`` — RULE 603.2's
    "for the first time each turn" phrasing exactly.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_triggered_ability",
                    {
                        "affects": "creatures_you_control",
                        "trigger_event": EventType.COUNTER,
                        "once_per_turn": True,
                        "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                    },
                )
            ],
        ),
    ]


register("Danny Pink", _danny_pink)

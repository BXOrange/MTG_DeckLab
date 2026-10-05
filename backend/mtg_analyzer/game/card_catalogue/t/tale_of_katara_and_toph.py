from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tale_of_katara_and_toph() -> list[AbilitySpec]:
    """Creatures you control have "Whenever this creature becomes tapped for
    the first time during each of your turns, put a +1/+1 counter on it."

    — PLAY-ALL Step 2 (Kodama). Danny Pink's `grant_triggered_ability` shape
    (layer 6, one `TriggeredAbility` per creature, ``once_per_turn`` for "for
    the first time") watching `EventType.TAPPED` instead of `COUNTER`, with
    ``controllers_turn_only`` for "during each of *your* turns". The counter
    goes on the granted creature itself (the trigger's own source, "it").
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_triggered_ability", {
                "affects": "creatures_you_control",
                "trigger_event": EventType.TAPPED,
                "once_per_turn": True,
                "controllers_turn_only": True,
                "grant_effects": [{"type": "add_counters", "params": {"count": 1, "kind": "+1/+1"}}],
            })],
        ),
    ]


register("Tale of Katara and Toph", _tale_of_katara_and_toph)

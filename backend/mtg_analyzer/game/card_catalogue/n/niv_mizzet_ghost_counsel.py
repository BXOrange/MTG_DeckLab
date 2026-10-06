from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [
        AbilitySpec("triggered", [EffectSpec("pay_cost_then", {
            "cost": "", "pay_life_x": True, "x_from_trigger_event": "amount",
            "effects": [{"type": "draw", "params": {"count": "$x"}}],
        })], trigger={"event": "LIFE_GAINED", "condition": {"subject": "you"}}),
        AbilitySpec("activated", [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}),
                                  EffectSpec("gain_life", {"amount": 1})], cost={"taps_self": True}),
    ]


register('Niv-Mizzet, Ghost Counsel', _card)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [
        AbilitySpec("static", [EffectSpec("prevent_all_life_gain", {"scope": "opponents"})]),
        AbilitySpec("triggered", [EffectSpec("for_each", {
            "over": {"players": "each_opponent"}, "effects": [{"type": "lose_life", "params": {
                "player": {"of": "target"},
                "amount": {"kind": "count_selector", "selector": "life_lost_this_turn", "of": "target"},
            }}],
        })], trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}}),
    ]


register('Archfiend of Despair', _card)

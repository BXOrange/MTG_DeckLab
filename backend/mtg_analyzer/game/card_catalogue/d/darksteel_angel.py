from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [
        AbilitySpec('static', [EffectSpec('cant_lose_game', {})]),
        AbilitySpec('static', [EffectSpec('opponents_cant_win', {})]),
        AbilitySpec('static', [EffectSpec('counter_placement_prohibition', {
            'affects': 'creatures_you_control', 'counter_kind': '-1/-1',
        })]),
    ]


register('Darksteel Angel', _card)

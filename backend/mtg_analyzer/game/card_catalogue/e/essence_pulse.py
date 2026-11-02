from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _essence_pulse() -> list[AbilitySpec]:
    'You gain 2 life. Each creature gets -X/-X until end of turn, where X is the amount of life you gained this turn.'
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('gain_life', {"amount": 2}), EffectSpec('pump', {"selector": 'all_creatures', "dynamic_amount": {'kind': 'count_selector', 'selector': 'life_gained_this_turn', 'multiply': -1}})],
            raw_text='',
        ),
    ]


register('Essence Pulse', _essence_pulse)

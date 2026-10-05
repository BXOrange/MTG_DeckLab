from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chitterspitter() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may sacrifice a token. If you do, put an acorn counter on this artifact.
    Squirrels you control get +1/+1 for each acorn counter on this artifact.
    {G}, {T}: Create a 1/1 green Squirrel creature token.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('pay_cost_then', {'cost': 'sacrifice a token',
                            'effects': [{'type': 'add_counters',
                                         'params': {'count': 1, 'kind': 'acorn'}}]}),
            ],
            trigger={'event': 'STEP_BEGIN',
                     'filter': {'step': 'upkeep'},
                     'phase_relation': 'you'},
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec('create_token', {'count': 1,
                            'power': 1,
                            'toughness': 1,
                            'colors': ['G'],
                            'subtypes': ['Squirrel'],
                            'keywords': [],
                            'token_name': 'Squirrel'}),
            ],
            cost={'text': '{g}, {t}'},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('anthem', {'affects': 'creatures_you_control',
                            'subtype': 'Squirrel',
                            'power': 1,
                            'toughness': 1,
                            'power_count': {'counters_on': 'source', 'kind': 'acorn'},
                            'toughness_count': {'counters_on': 'source', 'kind': 'acorn'}}),
            ],
        ),
    ]


register('Chitterspitter', _chitterspitter)

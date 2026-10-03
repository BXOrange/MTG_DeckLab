from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hazel_of_the_rootbloom() -> list[AbilitySpec]:
    """{T}, Pay 2 life, Tap X untapped tokens you control: Add X mana in any combination of colors.
    At the beginning of your end step, create a token that's a copy of target token you control. If that token is a Squirrel, instead create two tokens that are copies of it.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('if_else', {'condition': {'kind': 'is_subtype',
                                          'of': 'target',
                                          'subtype': 'Squirrel'},
                            'then': [{'type': 'copy_permanent',
                                      'params': {'count': 2,
                                                 'target_kind': 'token_you_control'}}],
                            'else': [{'type': 'copy_permanent',
                                      'params': {'count': 1,
                                                 'target_kind': 'token_you_control'}}]}),
            ],
            trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'end'}, 'phase_relation': 'you'},
        ),
    ]


register('Hazel of the Rootbloom', _hazel_of_the_rootbloom)

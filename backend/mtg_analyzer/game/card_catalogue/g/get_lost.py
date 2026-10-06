from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Destroy target creature, enchantment, or planeswalker. Its controller creates two Map
    tokens. (They're artifacts with "{1}, {T}, Sacrifice this token: Target creature you
    control explores. Activate only as a sorcery.")
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec(
                    'destroy',
                    {
                        'target_kind': 'permanent',
                        'creature_filter': {'card_type_any': ['creature', 'enchantment', 'planeswalker']},
                    },
                ),
                EffectSpec(
                    'create_token',
                    {
                        'token_name': 'Map',
                        'count': 2,
                        'creators': 'previous_target_controller',
                        'is_artifact': True,
                        'oracle_text': '{1}, {T}, Sacrifice this token: Target creature you control explores. Activate only as a sorcery.',
                    },
                ),
            ],
        ),
    ]


register('Get Lost', _specs)

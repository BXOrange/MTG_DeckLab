
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bloodletter() -> list[AbilitySpec]:
    'When the names of three or more nonland permanents begin with the same letter, sacrifice this creature. If you do, it deals 2 damage to each creature and each player.'
    return [AbilitySpec('triggered', [EffectSpec('seq', {
        'if_you_do_from': 1,
        'effects': [
            {'type': 'sacrifice_self', 'params': {'require_source_incarnation': True}},
            {'type': 'damage', 'params': {'amount': 2,
                'group': {'zone': 'battlefield', 'of': 'any', 'filter': {'card_type': 'creature'}},
                'group_and_players': 'each_player'}},
        ],
    })], trigger={'event': 'STATE_CHECK', 'state_condition': {
        'kind': 'control_count', 'min': 3,
        'selector': {'zone': 'battlefield', 'of': 'any', 'filter': {'without_card_type': 'land'},
                     'aggregate': 'max_shared_name_initial'},
    }})]



register('Bloodletter', _bloodletter)

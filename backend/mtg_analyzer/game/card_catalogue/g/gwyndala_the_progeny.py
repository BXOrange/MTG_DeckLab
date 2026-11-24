from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _gwyndala_the_progeny() -> list[AbilitySpec]:
    '''When Gwyndala enters, create a colorless Equipment artifact token named Neuroflux Heirloom with "Equipped creature gets +1/+1" and equip {2}. Attach it to Gwyndala.
    {2}: Each Equipment token you control becomes a copy of target Equipment you control until end of turn.'''
    return [
        AbilitySpec('triggered', [
            EffectSpec('create_token', {'count': 1, 'token_name': 'Neuroflux Heirloom',
                'is_artifact': True, 'colors': [], 'subtypes': ['Equipment'],
                'keywords': ['Equip'], 'oracle_text': 'Equipped creature gets +1/+1.\nEquip {2}'}),
            EffectSpec('attach', {'target_kind': 'source', 'mover': 'created_all', 'check_control': False}),
        ], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('activated', [EffectSpec('become_copy_of_target_until_eot', {
            'copy_target_kind': 'equipment_you_control', 'group_word': 'equipment_token',
        })], cost={'mana': '{2}'}),
    ]


register('Gwyndala, the Progeny', _gwyndala_the_progeny)

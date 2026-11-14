from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_needs_of_the_many() -> list[AbilitySpec]:
    '''As an additional cost to cast this spell, sacrifice a creature.
    Creatures you control gain hexproof and indestructible until end of turn. You gain hexproof until end of turn. Prevent all damage that would be dealt to you this turn. Exile The Needs of the Many.'''
    return [AbilitySpec('spell_effect', [
        EffectSpec('grant_until', {'duration': 'end_of_turn', 'lock_group': True, 'target_kind': None,
            'static': {'type': 'grant_keyword', 'params': {
                'affects': 'creatures_you_control', 'keywords': ['hexproof', 'indestructible']}}}),
        EffectSpec('grant_player_hexproof_until_eot', {}),
        EffectSpec('prevent_damage_shield', {'amount': 'all'}),
        EffectSpec('exile', {'target_kind': None}),
    ], additional_cost={'sacrifice': 'creature'})]


register('The Needs of the Many', _the_needs_of_the_many)

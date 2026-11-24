from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cherished_hatchling() -> list[AbilitySpec]:
    '''When this creature dies, you may cast Dinosaur spells this turn as though they had flash, and whenever you cast a Dinosaur spell this turn, it gains "When this creature enters, you may have it fight another target creature."'''
    return [AbilitySpec('triggered', [
        EffectSpec('grant_flash_until_eot', {'spell_filter': {'subtype': 'Dinosaur'}}),
        EffectSpec('create_turn_trigger', {
            'trigger': {'event': EventType.SPELL_CAST, 'condition': {'subject': 'you'},
                        'spell_filter': {'subtype': 'Dinosaur'}},
            'effects': [{'type': 'grant_until', 'params': {
                'target_kind': None, 'previous_subject': True, 'referent': 'trigger_subject',
                'duration': 'rest_of_game', 'static': {'type': 'grant_triggered_ability', 'params': {
                    'trigger_event': EventType.ENTERS_BATTLEFIELD, 'optional': True,
                    'grant_effects': [{'type': 'fight', 'params': {'other_kind': 'other_creature'}}],
                }},
            }}],
        }),
    ], trigger={'event': EventType.DIES, 'condition': {'subject': 'self'}})]


register('Cherished Hatchling', _cherished_hatchling)

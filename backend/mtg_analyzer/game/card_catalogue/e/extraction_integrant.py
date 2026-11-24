from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _extraction_integrant() -> list[AbilitySpec]:
    '''Artifact creatures you control have menace and "Whenever a creature blocks this creature, that creature gets -1/-1 until end of turn."'''
    return [
        AbilitySpec('static', [EffectSpec('grant_keyword', {
            'affects': {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature', 'all_of': [{'card_type': 'artifact'}]}}, 
            'keywords': ['menace'],
        })]),
        AbilitySpec('static', [EffectSpec('grant_triggered_ability', {
            'affects': {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature', 'all_of': [{'card_type': 'artifact'}]}}, 
            'trigger_event': 'BLOCKS', 'related_to_source': True,
            'grant_effects': [{'type': 'pump', 'params': {
                'power': -1, 'toughness': -1, 'trigger_subject': True,
            }}],
        })]),
    ]


register('Extraction Integrant', _extraction_integrant)

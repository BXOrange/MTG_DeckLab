from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ambulatory_reactor() -> list[AbilitySpec]:
    '''Artifact creatures you control have "{T}: Add {C}. Spend this mana only to cast an artifact spell or activate an ability of an artifact source."'''
    return [AbilitySpec('static', [EffectSpec('grant_mana_ability', {
        'affects': {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature'}}, 'object_filter': {'card_type': 'artifact'},
        'mana': [{'C': 1}],
        'mana_restriction': {'kind': 'card_type_spell', 'types': ['artifact'], 'allow_ability': True},
    })])]


register('Ambulatory Reactor', _ambulatory_reactor)

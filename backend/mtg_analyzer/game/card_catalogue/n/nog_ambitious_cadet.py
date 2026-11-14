from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nog_ambitious_cadet() -> list[AbilitySpec]:
    '''Menace
    {1}: If Nog is a Rogue, he becomes a Ferengi Scout with base power and toughness 3/4 and gains "Whenever Nog becomes tapped, surveil 2."
    {3}: If Nog is a Scout, he becomes a Ferengi Officer and gains "You may play lands from your graveyard" and "You may play an additional land on each of your turns."'''
    return [
        AbilitySpec('activated', [EffectSpec('if_else', {
            'condition': {'kind': 'is_subtype', 'subtype': 'Rogue'},
            'then': [{'type': 'grant_until', 'params': {
                'duration': 'rest_of_game', 'self_subject': True, 'target_kind': None,
                'static': {'type': 'type_change', 'params': {
                    'set_creature_types': ['Ferengi', 'Scout'], 'power': 3, 'toughness': 4}},
                'extra_statics': [{'type': 'grant_triggered_ability', 'params': {
                    'affects': 'self', 'trigger_event': 'TAPPED',
                    'grant_effects': [{'type': 'surveil', 'params': {'count': 2}}],
                }}],
            }}], 'else': [],
        })], cost={'mana': '{1}'}),
        AbilitySpec('activated', [EffectSpec('if_else', {
            'condition': {'kind': 'is_subtype', 'subtype': 'Scout'},
            'then': [{'type': 'grant_until', 'params': {
                'duration': 'rest_of_game', 'self_subject': True, 'target_kind': None,
                'static': {'type': 'type_change', 'params': {'set_creature_types': ['Ferengi', 'Officer']}},
                'extra_statics': [{'type': 'grant_static_ability', 'params': {
                    'affects': 'self', 'static_specs': [
                        {'type': 'graveyard_cast_permission', 'params': {'lands_only': True, 'once_per_turn': False}},
                        {'type': 'extra_land_drop', 'params': {'count': 1}},
                    ],
                }}],
            }}], 'else': [],
        })], cost={'mana': '{3}'}),
    ]


register('Nog, Ambitious Cadet', _nog_ambitious_cadet)

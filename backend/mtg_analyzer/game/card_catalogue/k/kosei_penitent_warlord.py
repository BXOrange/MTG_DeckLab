"""Kosei's continuously granted combat-damage ability."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kosei_penitent_warlord():
    '''As long as Kosei is enchanted, equipped, and has a counter on it, Kosei has "Whenever Kosei deals combat damage to an opponent, you draw that many cards and Kosei deals that much damage to each other opponent."'''
    return [AbilitySpec('static', [EffectSpec('grant_triggered_ability', {
        'affects': 'self',
        'active_if': {'kind': 'all', 'conditions': [
            {'kind': 'source_enchanted'}, {'kind': 'source_equipped'},
            {'kind': 'source_counters', 'min': 1},
        ]},
        'trigger_event': EventType.DAMAGE,
        'filter': {'combat': True, 'is_player': True},
        'recipient_relation': 'opponent',
        'grant_effects': [
            {'type': 'draw', 'params': {'count_from_trigger_event': 'amount'}},
            {'type': 'damage', 'params': {
                'selector': 'each_other_opponent', 'amount_from_trigger_event': 'amount',
            }},
        ],
    })])]


register('Kosei, Penitent Warlord', _kosei_penitent_warlord)

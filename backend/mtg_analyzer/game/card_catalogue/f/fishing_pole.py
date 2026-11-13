from __future__ import annotations
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _fishing_pole():
    'Equipped creature has "{1}, {T}, Tap Fishing Pole: Put a bait counter on Fishing Pole."\nWhenever equipped creature becomes untapped, remove a bait counter from this Equipment. If you do, create a 1/1 blue Fish creature token.\nEquip {2} ({2}: Attach to target creature you control. Equip only as a sorcery.)'
    return [
        AbilitySpec('static', [EffectSpec('grant_activated_ability', {
            'affects': 'attached_permanent',
            'cost': {'mana': '{1}', 'taps_self': True, 'tap_grant_source': True},
            'grant_effects': [{'type': 'add_counters', 'params': {'kind': 'bait', 'amount': 1, 'grantor_subject': True}}],
        })]),
        AbilitySpec('triggered', [EffectSpec('seq', {'effects': [
            {'type': 'remove_counters', 'params': {'self_only': True, 'kind': 'bait', 'count': 1}},
            {'type': 'create_token', 'params': {'count': 1, 'power': 1, 'toughness': 1, 'colors': ['U'], 'subtypes': ['Fish'], 'token_name': 'Fish'}},
        ], 'if_you_do_from': 1})], trigger={'event': EventType.UNTAPPED, 'condition': {'subject': 'attached_permanent'}}),
    ]
register('Fishing Pole', _fishing_pole)

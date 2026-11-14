from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _h_m_s_bounty_unlikely_timeship() -> list[AbilitySpec]:
    '''When H.M.S. Bounty enters, you may search your library for a Whale card, reveal it, put it into your hand, then shuffle.
    Station
    8+ | Flying
    Whenever H.M.S. Bounty deals combat damage to a player, draw a card. If you control a Whale and haven't begun an extra turn this game, take an extra turn after this one.'''
    return [
        AbilitySpec('triggered', [EffectSpec('search', {'criteria': {'type': 'whale'},
            'destination': 'hand', 'reveal': True})], optional=True,
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('static', [EffectSpec('grant_keyword', {'keywords': ['flying'],
            'affects': 'self', 'min_level': 8, 'level_counter': 'charge'})]),
        # Printed 3/4 at the 8+ Station level (TRK release notes, 2026-11-04, p. 30).
        AbilitySpec('static', [EffectSpec('type_change', {'add_types': ['creature'],
            'affects': 'self', 'min_level': 8, 'level_counter': 'charge', 'power': 3, 'toughness': 4})]),
        AbilitySpec('triggered', [EffectSpec('draw', {'count': 1}),
            EffectSpec('take_extra_turn', {}, condition={'kind': 'all', 'conditions': [
                {'kind': 'control_count', 'min': 1, 'selector': {
                    'zone': 'battlefield', 'of': 'you', 'filter': {'subtype': 'Whale'}}},
                {'kind': 'not', 'condition': {'kind': 'begun_extra_turn'}},
            ]})], trigger={'event': EventType.DAMAGE, 'condition': {'subject': 'self'},
                'filter': {'combat': True, 'is_player': True}, 'min_level': 8, 'level_counter': 'charge'}),
    ]


register('H.M.S. Bounty, Unlikely Timeship', _h_m_s_bounty_unlikely_timeship)

from __future__ import annotations
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _kjeldoran_guard():
    """{T}: Target creature gets +1/+1 until end of turn. When that creature leaves the battlefield this turn, sacrifice this creature. Activate only during combat and only if defending player controls no snow lands."""
    return [AbilitySpec('activated', [
        EffectSpec('pump', {'target_kind': 'creature', 'power': 1, 'toughness': 1}),
        EffectSpec('create_turn_trigger', {
            'trigger': {'event': EventType.LEAVES_BATTLEFIELD, 'condition': {'subject': 'self'}},
            'effects': [{'type': 'sacrifice_specific', 'params': {}}],
            'previous_subject': True, 'bake_source_object': True, 'once': True,
        }),
    ], cost={'text': '{T}', 'activation_condition': {'kind': 'all', 'conditions': [
        {'kind': 'during_phase', 'phase': 'combat'},
        {'kind': 'defending_player_permanent_count', 'filter': {'card_type': 'land', 'snow': True}, 'max': 0},
    ]}})]
register('Kjeldoran Guard', _kjeldoran_guard)

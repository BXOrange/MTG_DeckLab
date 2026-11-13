from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _giant_shark() -> list[AbilitySpec]:
    """This creature can't attack unless defending player controls an Island.
    Whenever this creature blocks or becomes blocked by a creature that has been dealt damage this turn, this creature gets +2/+0 and gains trample until end of turn.
    When you control no Islands, sacrifice this creature.
    """
    return [
        AbilitySpec('static', [EffectSpec('combat_restriction', {
            'kind': 'cant_attack_unless', 'condition': {'kind': 'defending_player_controls',
                'filter': {'subtype': 'Island'}}, 'affects': 'self',
        })]),
        *[AbilitySpec('triggered', [EffectSpec('pump', {
            'power': 2, 'toughness': 0, 'keywords': ['trample'], 'target_kind': None,
        })], trigger={'event': event, 'condition': {'subject': 'self'},
                     'related_filter': {'damaged_this_turn': True}})
          for event in (EventType.BLOCKS, EventType.BECOMES_BLOCKED_BY)],
        AbilitySpec('triggered', [EffectSpec('sacrifice_self', {})], trigger={
            'event': EventType.STATE_CHECK,
            'state_condition': {'kind': 'control_count', 'selector': {
                'zone': 'battlefield', 'of': 'you', 'filter': {'subtype': 'Island'},
            }, 'max': 0},
        }),
    ]


register('Giant Shark', _giant_shark)

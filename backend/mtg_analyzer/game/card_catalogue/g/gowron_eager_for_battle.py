from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _gowron_eager_for_battle() -> list[AbilitySpec]:
    '''Whenever another creature dies, put a +1/+1 counter on Gowron.
    Sacrifice another creature: Gowron gains trample until end of turn. If you sacrificed a Klingon this way, you draw a card and lose 1 life.'''
    return [
        AbilitySpec('triggered', [EffectSpec('add_counters', {'count': 1, 'kind': '+1/+1'})],
                    trigger={'event': EventType.DIES, 'condition': {
                        'subject': 'group', 'controller': 'any', 'other': True, 'type': 'creature'}}),
        AbilitySpec('activated', [
            EffectSpec('pump', {'keywords': ['trample']}),
            EffectSpec('if_else', {'condition': {'kind': 'sacrificed_cost_subtype', 'subtype': 'Klingon'},
                'then': [{'type': 'draw', 'params': {'count': 1}},
                         {'type': 'lose_life', 'params': {'amount': 1}}], 'else': []}),
        ], cost={'text': 'Sacrifice another creature'}),
    ]


register('Gowron, Eager for Battle', _gowron_eager_for_battle)

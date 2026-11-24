
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _zedruu_the_greathearted() -> list[AbilitySpec]:
    'At the beginning of your upkeep, you gain X life and draw X cards, where X is the number of permanents you own that your opponents control.\n{U}{R}{W}: Target opponent gains control of target permanent you control.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('give_control', {"recipient": 'target_opponent', "target_kind": 'permanent_you_control'})],
            cost={"text": '{u}{r}{w}'},
            raw_text='{u}{r}{w}: target opponent gains control of target permanent you control.',
        ),
        AbilitySpec('triggered', [EffectSpec('bind', {
            'name': 'donated', 'amount': {'kind': 'count_selector', 'selector': {
                'zone': 'battlefield', 'of': 'opponents', 'filter': {'owned_by_you': True},
            }},
            'effects': [
                {'type': 'gain_life', 'params': {'amount': '$donated'}},
                {'type': 'draw', 'params': {'count': '$donated'}},
            ],
        })], trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'upkeep'}, 'phase_relation': 'you'}),
    ]


register('Zedruu the Greathearted', _zedruu_the_greathearted)

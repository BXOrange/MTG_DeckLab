
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _vesuvan_drifter() -> list[AbilitySpec]:
    'Flying\nYou may look at the top card of your library any time.\nAt the beginning of each combat, you may reveal the top card of your library. If you reveal a creature card this way, this creature becomes a copy of that card until end of turn, except it has flying.'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('top_library_permission', {"look": True})],
            raw_text='you may look at the top card of your library any time.',
        ),
        AbilitySpec('triggered', [EffectSpec('optional', {'effects': [
            {'type': 'reveal_top', 'params': {}},
            {'type': 'become_copy_until_eot', 'params': {
                'copy_of_revealed': True, 'add_keywords': ['Flying'],
            }},
        ]})], trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'begin_combat'}}),
    ]


register('Vesuvan Drifter', _vesuvan_drifter)

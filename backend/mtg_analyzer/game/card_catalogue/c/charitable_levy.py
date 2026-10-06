from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Noncreature spells cost {1} more to cast.
    Whenever a player casts a noncreature spell, put a collection counter on this
    enchantment. Then if there are three or more collection counters on it, sacrifice it. If
    you do, draw a card, then you may search your library for a Plains card, put it onto the
    battlefield tapped, then shuffle.
    """
    return [
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'cost_reduction',
                    {
                        'affects': 'all_spells',
                        'generic': 1,
                        'increase': True,
                        'spell_type': 'noncreature',
                    },
                ),
            ],
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('add_counters', {'target_kind': None, 'kind': 'collection', 'amount': 1}),
                EffectSpec(
                    'sacrifice_source_then',
                    {
                        'then_specs': [
                            {'type': 'draw', 'params': {'count': 1}},
                            {
                                'type': 'search',
                                'params': {
                                    'criteria': {'type': 'Plains'},
                                    'destination': 'battlefield_tapped',
                                    'optional': True,
                                },
                            },
                        ],
                    },
                    condition={'kind': 'source_counters', 'counter': 'collection', 'min': 3},
                ),
            ],
            trigger={
                'event': EventType.SPELL_CAST,
                'any_player': True,
                'spell_exclude_card_types': ['creature'],
            },
        ),
    ]


register('Charitable Levy', _specs)

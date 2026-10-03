from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _skyfisher_spider() -> list[AbilitySpec]:
    """Reach
    When this creature enters, you may sacrifice another creature. When you do, destroy target nonland permanent.
    When this creature dies, you may gain 1 life for each creature card in your graveyard. If you do, exile this card from your graveyard.
    """
    return [
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'reach'},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('pay_cost_then', {'cost': 'sacrifice another creature',
                            'then_trigger': [{'type': 'destroy',
                                              'params': {'target_kind': 'nonland_permanent'}}]}),
            ],
            trigger={'event': 'ENTERS_BATTLEFIELD', 'condition': {'subject': 'self'}},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('gain_life', {'amount': 1, 'count_selector': 'creature_cards_in_your_graveyard'}),
                EffectSpec('exile', {'target_kind': None}),
            ],
            optional=True,
            trigger={'event': 'DIES', 'condition': {'subject': 'self'}},
        ),
    ]


register('Skyfisher Spider', _skyfisher_spider)

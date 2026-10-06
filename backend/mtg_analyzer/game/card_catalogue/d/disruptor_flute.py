from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Flash
    As this artifact enters, choose a card name.
    Spells with the chosen name cost {3} more to cast.
    Activated abilities of sources with the chosen name can't be activated unless they're
    mana abilities.
    """
    return [
        AbilitySpec(
            'enter_replacement',
            [EffectSpec('choose_card_name_on_enter', {})],
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'cost_reduction',
                    {
                        'affects': 'all_spells',
                        'generic': 3,
                        'increase': True,
                        'card_name_from_source': True,
                    },
                ),
                EffectSpec(
                    'activation_prohibition',
                    {
                        'affects': 'all_permanents',
                        'card_name_from_source': True,
                        'except_mana_abilities': True,
                    },
                ),
            ],
        ),
    ]


register('Disruptor Flute', _specs)

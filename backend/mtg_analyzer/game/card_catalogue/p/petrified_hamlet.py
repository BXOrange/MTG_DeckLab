from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    When this land enters, choose a land card name.
    Activated abilities of sources with the chosen name can't be activated unless they're
    mana abilities.
    Lands with the chosen name have "{T}: Add {C}."
    {T}: Add {C}.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec(
                    'name_card_then',
                    {
                        'effects': [
                            {
                                'type': 'remember_card_name',
                                'params': {'name': 'named_card', 'card_type': 'land'},
                            },
                        ],
                    },
                ),
            ],
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'activation_prohibition',
                    {
                        'affects': 'all_permanents',
                        'card_name_from_source': True,
                        'except_mana_abilities': True,
                    },
                ),
                EffectSpec(
                    'grant_mana_ability',
                    {'affects': 'all_lands', 'card_name_from_source': True, 'mana': [{'C': 1}]},
                ),
            ],
        ),
    ]


register('Petrified Hamlet', _specs)

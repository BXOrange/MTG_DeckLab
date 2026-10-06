from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """Flying, trample, haste
    As long as there are fewer than eight cards in your graveyard, The Warring Triad isn't a creature.
    {T}, Mill a card: Target player adds one mana of any color. (Activate only as an instant.)
    """
    return [
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'type_change',
                    {
                        'affects': 'self',
                        'remove_types': ['creature'],
                        'active_if': {
                            'kind': 'control_count',
                            'selector': {'zone': 'graveyard', 'of': 'you'},
                            'max': 7,
                        },
                    },
                ),
            ],
        ),
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'add_mana',
                    {'colors': ['ANY'], 'recipient': 'target_player', 'target_kind': 'player'},
                ),
            ],
            cost={'text': '{T}, Mill a card'},
        ),
    ]


register('The Warring Triad', _specs)

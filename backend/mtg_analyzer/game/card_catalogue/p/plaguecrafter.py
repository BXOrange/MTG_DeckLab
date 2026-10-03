from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _plaguecrafter() -> list[AbilitySpec]:
    """When this creature enters, each player sacrifices a creature or planeswalker of their choice. Each player who can't discards a card.
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec('for_each', {'over': {'players': 'each_player'},
                            'effects': [{'type': 'sacrifice_permanent_or_discard',
                                         'params': {}}]}),
            ],
            trigger={'event': 'ENTERS_BATTLEFIELD', 'condition': {'subject': 'self'}},
        ),
    ]


register('Plaguecrafter', _plaguecrafter)

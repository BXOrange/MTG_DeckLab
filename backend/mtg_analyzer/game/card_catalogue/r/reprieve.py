from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Return target spell to its owner's hand.
    Draw a card.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('return_to_hand', {'target_kind': 'spell', 'spell_or_permanent': True}),
                EffectSpec('draw', {'count': 1}),
            ],
        ),
    ]


register('Reprieve', _specs)

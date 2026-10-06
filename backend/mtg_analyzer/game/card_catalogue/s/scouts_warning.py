from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    The next creature card you play this turn can be played as though it had flash.
    Draw a card.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('grant_flash_until_eot', {'card_types': ['creature'], 'next_only': True}),
                EffectSpec('draw', {'count': 1}),
            ],
        ),
    ]


register("Scout's Warning", _specs)

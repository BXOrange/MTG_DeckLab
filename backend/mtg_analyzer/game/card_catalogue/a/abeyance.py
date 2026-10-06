from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Until end of turn, target player can't cast instant or sorcery spells, and that player
    can't activate abilities that aren't mana abilities.
    Draw a card.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec(
                    'restrict_target_player_this_turn',
                    {'spell_types': ['instant', 'sorcery'], 'activations': True},
                ),
                EffectSpec('draw', {'count': 1}),
            ],
        ),
    ]


register('Abeyance', _specs)

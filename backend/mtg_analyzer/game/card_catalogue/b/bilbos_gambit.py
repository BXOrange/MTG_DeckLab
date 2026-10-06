from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Gift a Treasure (You may promise an opponent a gift as you cast this spell. If you do,
    they create a Treasure token before its other effects. It's an artifact with "{T},
    Sacrifice this token: Add one mana of any color.")
    Return target spell to its owner's hand. If the gift was promised, players can't cast
    spells this turn.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('return_to_hand', {'target_kind': 'spell', 'spell_or_permanent': True}),
                EffectSpec(
                    'grant_until',
                    {
                        'static': {'type': 'cast_prohibition', 'params': {'scope': 'all'}},
                        'duration': 'end_of_turn',
                        'target_kind': None,
                    },
                    condition={'gift_promised': True},
                ),
            ],
        ),
    ]


register("Bilbo's Gambit", _specs)

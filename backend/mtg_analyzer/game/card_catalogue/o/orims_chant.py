from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Kicker {W} (You may pay an additional {W} as you cast this spell.)
    Target player can't cast spells this turn. If this spell was kicked, creatures can't
    attack this turn.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('restrict_target_player_this_turn', {}),
                EffectSpec(
                    'grant_until',
                    {
                        'static': {
                            'type': 'grant_keyword',
                            'params': {'affects': 'all_creatures', 'keywords': ['cant_attack']},
                        },
                        'duration': 'end_of_turn',
                        'target_kind': None,
                    },
                    condition={'kicked': True},
                ),
            ],
        ),
    ]


register("Orim's Chant", _specs)

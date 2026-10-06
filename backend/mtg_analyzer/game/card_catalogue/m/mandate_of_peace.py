from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Cast this spell only during combat.
    Your opponents can't cast spells this turn.
    End the combat phase. (Remove all attackers and blockers from combat. Exile all spells
    and abilities from the stack, including this spell.)
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec(
                    'grant_until',
                    {
                        'static': {'type': 'cast_prohibition', 'params': {'scope': 'opponents'}},
                        'duration': 'end_of_turn',
                        'target_kind': None,
                    },
                ),
                EffectSpec('end_combat_phase', {}),
            ],
            cast_timing_restriction={'phase': 'combat'},
        ),
    ]


register('Mandate of Peace', _specs)

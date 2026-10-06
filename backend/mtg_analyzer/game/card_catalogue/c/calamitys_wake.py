from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Exile all graveyards. Players can't cast noncreature spells this turn. Exile Calamity's
    Wake.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('exile_all_graveyards', {}),
                EffectSpec(
                    'grant_until',
                    {
                        'static': {'type': 'cast_prohibition', 'params': {'scope': 'all', 'noncreature': True}},
                        'duration': 'end_of_turn',
                        'target_kind': None,
                    },
                ),
                EffectSpec('exile', {'target_kind': None}),
            ],
        ),
    ]


register("Calamity's Wake", _specs)

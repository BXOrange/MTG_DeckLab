from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _saw_in_half() -> list[AbilitySpec]:
    """Destroy target creature. If that creature dies this way, its controller creates two tokens that are copies of that creature, except their power is half that creature's power and their toughness is half that creature's toughness. Round up each time.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('destroy_and_half_copies', {}),
            ],
        ),
    ]


register('Saw in Half', _saw_in_half)

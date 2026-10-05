from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _maelstrom_pulse() -> list[AbilitySpec]:
    """Destroy target nonland permanent and all other permanents with the same name as that permanent.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [
                EffectSpec('destroy_same_name', {}),
            ],
        ),
    ]


register('Maelstrom Pulse', _maelstrom_pulse)

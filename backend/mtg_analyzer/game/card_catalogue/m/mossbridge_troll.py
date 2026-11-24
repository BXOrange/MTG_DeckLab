
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mossbridge_troll() -> list[AbilitySpec]:
    'If this creature would be destroyed, regenerate it.\nTap any number of untapped creatures you control other than this creature with total power 10 or greater: This creature gets +20/+20 until end of turn.'
    return [AbilitySpec('replacement', [EffectSpec('regenerate_self', {})]),
            AbilitySpec('activated', [EffectSpec('pump', {'power': 20, 'toughness': 20, 'target_kind': None})],
                        cost={'tap_total_power': 10})]


register('Mossbridge Troll', _mossbridge_troll)

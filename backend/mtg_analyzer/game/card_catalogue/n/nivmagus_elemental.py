from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nivmagus_elemental() -> list[AbilitySpec]:
    "Exile an instant or sorcery spell you control: Put two +1/+1 counters on this creature. (That spell won't resolve.)"
    return [AbilitySpec('activated', [EffectSpec('add_counters', {'kind': '+1/+1', 'count': 2})],
                        cost={'exile_instant_or_sorcery_spell': True})]


register('Nivmagus Elemental', _nivmagus_elemental)

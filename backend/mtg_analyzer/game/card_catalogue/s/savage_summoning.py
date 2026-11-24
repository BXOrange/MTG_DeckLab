from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _savage_summoning() -> list[AbilitySpec]:
    """This spell can't be countered.
    The next creature spell you cast this turn can be cast as though it had flash. That spell can't be countered. That creature enters with an additional +1/+1 counter on it.
    """
    return [AbilitySpec('spell_effect', [
        EffectSpec('cant_be_countered', {}),
        EffectSpec('grant_flash_until_eot', {
            'card_types': ['creature'], 'next_only': True,
            'cant_be_countered': True, 'entry_counters': {'+1/+1': 1},
        }),
    ])]


register('Savage Summoning', _savage_summoning)

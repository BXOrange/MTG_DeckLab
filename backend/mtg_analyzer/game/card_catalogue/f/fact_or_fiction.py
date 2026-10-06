from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [AbilitySpec('spell_effect', [EffectSpec('reveal_split_piles', {'count': 5})])]


register('Fact or Fiction', _card)

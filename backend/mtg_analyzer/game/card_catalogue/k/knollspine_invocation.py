from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _knollspine_invocation() -> list[AbilitySpec]:
    '{X}, Discard a card with mana value X: This enchantment deals X damage to any target.'
    return [AbilitySpec('activated', [EffectSpec('damage', {'amount': 'x', 'target_kind': 'any'})],
                        cost={'mana': '{X}', 'discard': 1, 'discard_mana_value_x': True})]


register('Knollspine Invocation', _knollspine_invocation)

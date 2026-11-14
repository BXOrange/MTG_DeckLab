from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _silver_scrutiny() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash if X is 3 or less.
    Draw X cards.
    """
    return [AbilitySpec('spell_effect', [EffectSpec('draw', {'count': 'x'})],
                        conditional_flash={'active_if': {'kind': 'x_paid', 'max': 3}})]


register('Silver Scrutiny', _silver_scrutiny)

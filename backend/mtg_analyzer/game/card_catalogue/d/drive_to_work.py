from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _drive_to_work():
    """Exile target creature or Vehicle. At the beginning of the next end step, return that card to the battlefield under its owner's control. Then you may share a story or fun fact about that card. If you do, you gain 3 life."""
    return [AbilitySpec('spell_effect', [EffectSpec('drive_to_work', {})])]


register('Drive to Work', _drive_to_work)

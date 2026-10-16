from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _now_you_see_me():
    """Exile target creature you control, then return it to the battlefield under its owner's control with X +1/+1 counters on it, where X is the number of mirrors on walls you can see from your seat."""
    return [AbilitySpec('spell_effect', [EffectSpec('mirror_flicker', {})])]


register('Now You See Me . . .', _now_you_see_me)

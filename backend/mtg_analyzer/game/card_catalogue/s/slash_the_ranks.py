
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _slash_the_ranks() -> list[AbilitySpec]:
    'Destroy all creatures and planeswalkers except for commanders.'
    return [
        AbilitySpec("spell_effect", [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type_any": ["creature", "planeswalker"], "is_commander": False}}})]),
    ]


register('Slash the Ranks', _slash_the_ranks)

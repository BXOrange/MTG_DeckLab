
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hugh_first_of_many() -> list[AbilitySpec]:
    'Artifact spells you cast have replicate {2}{U}. (Whenever you cast an artifact spell, copy it for each time you paid its replicate cost. Each copy becomes a token.)'
    return [
        AbilitySpec("static", [EffectSpec("grant_replicate", {"cost": "{2}{U}"})]),
    ]


register('Hugh, First of Many', _hugh_first_of_many)

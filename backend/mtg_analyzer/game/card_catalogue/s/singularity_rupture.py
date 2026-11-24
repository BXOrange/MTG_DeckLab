
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _singularity_rupture() -> list[AbilitySpec]:
    'Destroy all creatures, then any number of target players each mill half their library, rounded down.'
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}}),
            EffectSpec("mill", {"target_kind": "player", "any_number_of_players": True, "half": "down"}),
        ]),
    ]


register('Singularity Rupture', _singularity_rupture)

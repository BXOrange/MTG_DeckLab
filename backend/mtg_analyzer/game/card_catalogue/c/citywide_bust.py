from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _citywide_bust() -> list[AbilitySpec]:
    """Destroy all creatures with toughness 4 or greater."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_toughness": 4}})],
        )
    ]


register("Citywide Bust", _citywide_bust)

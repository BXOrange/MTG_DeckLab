from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _70_000_light_years_from_home() -> list[AbilitySpec]:
    """Exile target creature or Spacecraft. Its controller may search their library for a basic land card, reveal it, put it into their hand, then shuffle."""
    return [AbilitySpec("spell_effect", [EffectSpec(
        "exile_controller_searches_basic_land",
        {"target_kind": "creature_or_spacecraft", "destination": "hand",
         "optional": True, "reveal": True},
    )])]


register("70,000 Light-Years from Home", _70_000_light_years_from_home)

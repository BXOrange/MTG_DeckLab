from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wrath_of_god() -> list[AbilitySpec]:
    """Destroy all creatures. They can't be regenerated."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "can_be_regenerated": False})],
        )
    ]


register("Wrath of God", _wrath_of_god)

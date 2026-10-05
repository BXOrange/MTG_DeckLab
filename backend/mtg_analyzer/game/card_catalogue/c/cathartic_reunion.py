from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cathartic_reunion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, discard two cards.
    Draw three cards."""
    return [
        AbilitySpec(
            "spell_effect", [EffectSpec("draw", {"count": 3})],
            additional_cost={"discard": 2},
        )
    ]


register("Cathartic Reunion", _cathartic_reunion)

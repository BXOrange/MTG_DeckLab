from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _open_the_armory() -> list[AbilitySpec]:
    """Search your library for an Aura or Equipment card, reveal it, put it
    into your hand, then shuffle.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {"criteria": {"type": ["Aura", "Equipment"]}, "destination": "hand"})],
        )
    ]


register("Open the Armory", _open_the_armory)

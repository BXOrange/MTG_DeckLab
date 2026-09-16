from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _expansion_algorithm() -> list[AbilitySpec]:
    """Proliferate X times."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("proliferate", {"times": "x"})],
        ),
    ]


register("Expansion Algorithm", _expansion_algorithm)

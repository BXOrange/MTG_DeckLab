from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _go_for_the_throat() -> list[AbilitySpec]:
    """Destroy target nonartifact creature."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"without_card_type": "artifact"}})],
        ),
    ]


register("Go for the Throat", _go_for_the_throat)

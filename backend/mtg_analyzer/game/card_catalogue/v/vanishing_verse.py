from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Vanishing Verse (new target kind) + two manland/token singletons
# ===========================================================================
# Engine: `targeting` target kind ``monocolored_permanent`` (Vanishing Verse).


def _vanishing_verse() -> list[AbilitySpec]:
    """Exile target monocolored permanent."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {"target_kind": "monocolored_permanent"})],
        ),
    ]


register("Vanishing Verse", _vanishing_verse)

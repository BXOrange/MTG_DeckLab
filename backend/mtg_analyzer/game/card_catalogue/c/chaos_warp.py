from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Chaos Warp (shuffle a permanent away + reveal-top) — PAR-60
# ===========================================================================
# New `shuffle_target_into_library_reveal_top` effect.


def _chaos_warp() -> list[AbilitySpec]:
    """The owner of target permanent shuffles it into their library, then
    reveals the top card of their library. If it's a permanent card, they
    put it onto the battlefield."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("shuffle_target_into_library_reveal_top",
                        {"target_kind": "permanent"})],
        ),
    ]


register("Chaos Warp", _chaos_warp)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reality_shift() -> list[AbilitySpec]:
    """Exile target creature. Its controller manifests the top card of their library."""
    return [AbilitySpec(
        "spell_effect",
        [
            EffectSpec("exile", {"target_kind": "creature"}),
            EffectSpec("manifest", {"player": "previous_target_controller"}),
        ],
    )]


register("Reality Shift", _reality_shift)

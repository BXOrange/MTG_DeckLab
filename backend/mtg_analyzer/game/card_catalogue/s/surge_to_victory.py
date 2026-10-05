from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Surge to Victory (exile i/s from gy + team anthem) — PAR-60
# ===========================================================================
# New `surge_to_victory` effect. Documented simplification: the "whenever a
# creature deals combat damage, copy the exiled card and cast it free"
# rider is dropped (no per-firing copy-a-remembered-exiled-card primitive).


def _surge_to_victory() -> list[AbilitySpec]:
    """Exile target instant or sorcery card from your graveyard. Creatures
    you control get +X/+0 until end of turn, where X is that card's mana
    value. Whenever a creature you control deals combat damage to a player
    this turn, copy the exiled card. You may cast the copy without paying
    its mana cost."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("surge_to_victory", {})],
        ),
    ]


register("Surge to Victory", _surge_to_victory)

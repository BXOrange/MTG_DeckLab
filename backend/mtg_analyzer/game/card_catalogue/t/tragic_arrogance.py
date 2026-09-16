from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Tragic Arrogance (mass keep-one-of-each) — PAR-60
# ===========================================================================
# New `tragic_arrogance` effect. Documented simplification: the caster's
# per-(player, type) choice is auto-resolved — keep the highest-MV of each
# type among the caster's own permanents, the lowest-MV among opponents'.


def _tragic_arrogance() -> list[AbilitySpec]:
    """For each player, you choose from among the permanents that player
    controls an artifact, a creature, an enchantment, and a planeswalker.
    Then each player sacrifices all other nonland permanents they control."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("tragic_arrogance", {})],
        ),
    ]


register("Tragic Arrogance", _tragic_arrogance)

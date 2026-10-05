from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fireblast() -> list[AbilitySpec]:
    """You may sacrifice two Mountains rather than pay this spell's mana
    cost.
    Fireblast deals 4 damage to any target.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. **Documented simplification**: the alternative
    "sacrifice two Mountains instead of paying mana" cost isn't modeled —
    this engine's cost vocabulary has no free-alternative-cost concept
    (RULE 601.2f's own free-cast condition gate is for a fixed condition,
    not a player-chosen cost substitution); the spell is fully castable
    at its normal printed mana cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        ),
    ]


register("Fireblast", _fireblast)

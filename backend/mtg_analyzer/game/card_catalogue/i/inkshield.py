from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Inkshield (prevent combat damage to you -> tokenize) — PAR-60
# ===========================================================================
# Reuses `RulesEngine.prevent_damage_to_player`'s existing ``rider`` hook
# (`apply_prevent_rider`'s ``create_tokens_scaled`` kind — Bone Mask /
# New Way Forward family) plus a new ``combat_only`` flag on the "…to you"
# shield. No new effect class.


def _inkshield() -> list[AbilitySpec]:
    """Prevent all combat damage that would be dealt to you this turn. For
    each 1 damage prevented this way, create a 2/1 white and black Inkling
    creature token with flying."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all",
                "combat_only": True,
                "rider": {
                    "kind": "create_tokens_scaled",
                    "recipient": "you",
                    "token": {
                        "token_name": "Inkling", "power": 2, "toughness": 1,
                        "colors": ["W", "B"], "subtypes": ["Inkling"],
                        "keywords": ["flying"],
                    },
                },
            })],
        ),
    ]


register("Inkshield", _inkshield)

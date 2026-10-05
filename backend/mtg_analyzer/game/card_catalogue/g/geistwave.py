from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geistwave() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card.

    Check control before the zone change (RULE 608.2h): returning the
    permanent restores its owner's control and clears its battlefield state.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("if_else", {
                    "condition": {"kind": "is_you", "of": "target"},
                    "then": [
                        {"type": "return_to_hand", "params": {
                            "target_kind": "nonland_permanent",
                        }},
                        {"type": "draw", "params": {"count": 1}},
                    ],
                    "else": [{"type": "return_to_hand", "params": {
                        "target_kind": "nonland_permanent",
                    }}],
                }),
            ],
        )
    ]


register("Geistwave", _geistwave)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

_ANY_COLOR = [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def _esika_god_of_the_tree() -> list[AbilitySpec]:
    """Vigilance
    {T}: Add one mana of any color.
    Other legendary creatures you control have vigilance and "{T}: Add one
    mana of any color."

    — PLAY-ALL Step 2 (SpongeBob). Vigilance and Esika's own {T}: Add one mana
    of any color are read off the card's text. The grant is two statics on
    ``other_creatures_you_control`` filtered to legendary ones: a
    `grant_keyword` for vigilance and the parser's `grant_mana_ability` (the
    five-color option list) for the quoted mana ability. This registers the
    front face only — the cache holds just that face of the double-faced card
    (the back, The Prismatic Bridge, is not in it, so it is not authored here).
    """
    legendary = {"legendary": True}
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": dict(legendary),
                "keywords": ["vigilance"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "mana": [dict(option) for option in _ANY_COLOR],
                "affects": "other_creatures_you_control", "object_filter": dict(legendary),
            })],
        ),
    ]


register("Esika, God of the Tree", _esika_god_of_the_tree)

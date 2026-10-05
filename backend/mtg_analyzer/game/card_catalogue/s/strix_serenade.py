from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _strix_serenade() -> list[AbilitySpec]:
    """Counter target artifact, creature, or planeswalker spell. Its
    controller creates a 2/2 blue Bird creature token with flying.

    — Strix Serenade. Swan Song's mirror over the other card-type triplet
    (ENG-37 B3: `seq` of `counter` + `create_token` with
    ``creators="previous_target_controller"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {
                    "card_types": ["artifact", "creature", "planeswalker"],
                }},
                {"type": "create_token", "params": {
                    "power": 2, "toughness": 2, "colors": ["U"],
                    "subtypes": ["Bird"], "keywords": ["flying"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Strix Serenade", _strix_serenade)

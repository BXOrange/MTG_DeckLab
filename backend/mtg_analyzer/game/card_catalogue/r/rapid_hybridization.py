from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rapid_hybridization() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. That creature's
    controller creates a 3/3 green Frog Lizard creature token.

    — Rapid Hybridization. Pongify's blue sibling (ENG-37 B3: `seq` of
    `destroy` + `create_token` with ``creators="previous_target_controller"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {
                    "target_kind": "creature", "can_be_regenerated": False,
                }},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Frog", "Lizard"], "token_name": "Frog Lizard",
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Rapid Hybridization", _rapid_hybridization)

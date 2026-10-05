from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stroke_of_midnight() -> list[AbilitySpec]:
    """Destroy target nonland permanent. Its controller creates a 1/1 white Human creature token.

    — Stroke of Midnight. Pongify's shape: `destroy` then `create_token` for the previous target's controller.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {"target_kind": "nonland_permanent"}},
                {"type": "create_token", "params": {
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Human"],
                    "token_name": "Human", "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Stroke of Midnight", _stroke_of_midnight)

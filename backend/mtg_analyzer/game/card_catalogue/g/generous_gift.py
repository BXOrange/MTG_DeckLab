from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _generous_gift() -> list[AbilitySpec]:
    """Destroy target permanent. Its controller creates a 3/3 green Elephant
    creature token.

    — PLAY-ALL Step 2 (yshtola). Beast Within's exact shape (a `seq` of
    `destroy` then `create_token` for ``previous_target_controller``, RULE
    608.2h last-known controller), with a different token subtype.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {"target_kind": "permanent"}},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Elephant"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Generous Gift", _generous_gift)

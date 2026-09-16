from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beast_within() -> list[AbilitySpec]:
    """Destroy target permanent. Its controller creates a 3/3 green Beast
    creature token.

    — Beast Within. ENG-37 B3: a `seq` of `destroy` then `create_token` with
    ``creators="previous_target_controller"`` (the destroyed permanent's
    last-known controller, RULE 608.2h — it survives the move to the
    graveyard), retiring the fused ``destroy_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {"target_kind": "permanent"}},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Beast"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Beast Within", _beast_within)

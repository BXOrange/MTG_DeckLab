from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Batch 14 — "destroy/counter target X; its controller creates a token"
# cluster and further cube singles whose effect primitives already exist.
# ---------------------------------------------------------------------------


def _pongify() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    creates a 3/3 green Ape creature token.

    — Pongify. ENG-37 B3: a `seq` of `destroy` (``can_be_regenerated=False``
    for the "can't be regenerated" clause) then `create_token` with
    ``creators="previous_target_controller"``, retiring the fused
    ``destroy_create_token``.
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
                    "subtypes": ["Ape"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Pongify", _pongify)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crib_swap() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    Exile target creature. Its controller creates a 1/1 colorless
    Shapeshifter creature token with changeling.

    The one-card token-replacement shape is not worth a parser row (the
    cache probe finds Crib Swap alone). ENG-37 B3: a `seq` of `exile` then
    `create_token` with ``creators="previous_target_controller"`` (reads the
    exiled creature's last-known controller, RULE 608.2h), retiring the fused
    ``exile_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile", "params": {"target_kind": "creature"}},
                {"type": "create_token", "params": {
                    "power": 1, "toughness": 1, "subtypes": ["Shapeshifter"],
                    "keywords": ["changeling"], "token_name": "Shapeshifter",
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Crib Swap", _crib_swap)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crypt_incursion() -> list[AbilitySpec]:
    """Exile all creature cards from target player's graveyard. You gain 3
    life for each card exiled this way.

    ENG-37 B3: a `seq` of `exile_target_graveyard` (``card_type="creature"``)
    then a `bind` measuring ``objects_exiled_this_way`` (×3) into `gain_life`
    — retiring the fused `exile_graveyard_creatures_gain_life`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_target_graveyard",
                 "params": {"target_kind": "player", "card_type": "creature"}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "this_way", "tally": "objects_exiled_this_way",
                               "multiply": 3},
                    "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
                }},
            ]})],
        )
    ]


register("Crypt Incursion", _crypt_incursion)

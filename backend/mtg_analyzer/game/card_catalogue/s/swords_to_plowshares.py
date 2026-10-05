from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swords_to_plowshares() -> list[AbilitySpec]:
    """Exile target creature. Its controller gains life equal to its power.

    ENG-37: the first fused effect type retired onto the composition axis.
    This shipped as one welded `exile_gain_life_equal_power` class whose own
    docstring explained why it had to be — "`GainLifeEffect` deliberately
    never reads a shared ``targets`` list, so composing two effects here
    couldn't pass the power along". That was true of the *operand* axis, not
    of composition: the life is measured off the exiled creature and paid to
    **its** controller, and neither the amount nor the recipient could name a
    referent. `effect_amounts` supplies the first and `effect_operands` the
    second, so the card is now what it reads as — an exile, then a life gain
    that points back at what the exile chose.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {"target_kind": "creature"}),
                EffectSpec("bind", {
                    "name": "power",
                    "amount": {
                        "kind": "characteristic", "characteristic": "power",
                        "of": "previous_target",
                    },
                    "effects": [{
                        "type": "gain_life",
                        "params": {
                            "amount": "$power",
                            "player": {"of": "previous_target", "as": "controller"},
                        },
                    }],
                }),
            ],
        )
    ]


register("Swords to Plowshares", _swords_to_plowshares)

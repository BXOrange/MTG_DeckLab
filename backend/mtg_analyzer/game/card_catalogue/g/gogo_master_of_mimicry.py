from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gogo_master_of_mimicry() -> list[AbilitySpec]:
    """{X}{X}, {T}: Copy target activated or triggered ability you control X
    times. You may choose new targets for the copies. This ability can't be
    copied and X can't be 0. (Mana abilities can't be targeted.)

    — PLAY-ALL: announces a positive X, targets an ability you control,
    and offers each copy's targets before any copy enters the stack.
    The stack item retains the prohibition on copying this ability.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("copy_target_ability", {})],
            cost={"text": "{X}{X}, {T}", "minimum_x": 1, "cant_be_copied": True},
        ),
    ]


register("Gogo, Master of Mimicry", _gogo_master_of_mimicry)

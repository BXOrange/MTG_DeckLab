from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gogo_master_of_mimicry() -> list[AbilitySpec]:
    """{X}{X}, {T}: Copy target activated or triggered ability you control X
    times. You may choose new targets for the copies. This ability can't be
    copied and X can't be 0. (Mana abilities can't be targeted.)

    — PLAY-ALL Step 2 (SpongeBob). The new `copy_target_ability` effect
    (`stack.CopyTargetAbilityEffect`): a ``TargetSpec(kind="ability")`` target
    (an ability item on the stack, by `stack_id`), then ``X`` calls to
    `copy_ability` — the targeted sibling of Rings of Brighthearth's "copy that
    ability". The ``{X}{X}`` cost announces X once (``x_paid``). Documented
    simplifications: the copies keep the original's targets; "can't be 0" is
    not enforced as a casting rule (X = 0 just copies nothing); "this ability
    can't be copied" holds trivially since Gogo's own ability has already left
    the stack by the time it resolves.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("copy_target_ability", {})],
            cost={"text": "{X}{X}, {T}"},
        ),
    ]


register("Gogo, Master of Mimicry", _gogo_master_of_mimicry)

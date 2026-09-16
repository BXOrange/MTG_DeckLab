from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chain_of_smog() -> list[AbilitySpec]:
    """Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy.

    — MEC-43. The discard is ordinary; the copy is the new
    `CopySelfControlledByPreviousTargetEffect` — the discard target
    (`GameContext.previous_targets`) becomes the copy's controller,
    mirroring `CopySelfIfCastFromGraveyardEffect`'s own "may" simplification
    (always copies, keeps the same target) rather than opening a fresh
    interactive retarget.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 2, "target_kind": "player"}),
                EffectSpec("copy_self_spell", {
                    "controller": {"of": "target", "as": "self"},
                }),
            ],
        ),
    ]


register("Chain of Smog", _chain_of_smog)

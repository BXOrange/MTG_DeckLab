from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _torch_breath() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if it targets a blue permanent.
    This spell can't be countered.
    Torch Breath deals X damage to target creature or planeswalker.

    — Imodane deck batch. **Documented simplification**: the target-
    dependent cost reduction isn't modeled (RULE 601.2f cost reduction is
    a board-state/count-selector concept everywhere else in this catalogue;
    a reduction keyed off a target chosen *during the same cast* is a
    different, unbuilt timing shape) — the spell is fully castable at its
    normal printed cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("damage", {"amount": "x", "target_kind": "creature_or_planeswalker"}),
            ],
        ),
    ]


register("Torch Breath", _torch_breath)

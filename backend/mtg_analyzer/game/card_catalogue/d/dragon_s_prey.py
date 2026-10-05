from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dragon_s_prey() -> list[AbilitySpec]:
    """This spell costs {2} more to cast if it targets a Dragon.
    Destroy target creature.

    — PLAY-ALL Step 2 (yshtola). The destroy is the ordinary targeted
    `destroy`. The tax is a self-scoped (``affects: self``, read off the spell
    in hand by `continuous.self_cost_reduction_for`) `cost_reduction` with
    ``increase`` and Killian's ``reduce_if_targets`` gate naming a Dragon (a
    type-line match). A tax needs the chosen targets, so the offer-time probe —
    which has none — now skips it instead of assuming the worst case.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2, "increase": True,
                "reduce_if_targets": {"card_type": "dragon"},
            })],
        ),
        AbilitySpec("spell_effect", [EffectSpec("destroy", {"target_kind": "creature"})]),
    ]


register("Dragon's Prey", _dragon_s_prey)

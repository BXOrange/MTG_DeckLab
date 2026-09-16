from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _defense_grid() -> list[AbilitySpec]:
    """Each spell costs {3} more to cast except during its controller's turn.

    — MEC-12 (cEDH staples/staples 2). A genuinely new `cost_reduction`
    rider, `except_caster_own_turn` — "its controller" means the *taxed
    spell's own caster*, not Defense Grid's controller, so it can't reuse
    the ordinary ability-source-relative `active_if`/`your_turn` gate the
    way Tithe Taker's own "during your turn" clause does; `continuous.
    cost_reduction_for` checks it directly against its own ``player``
    argument instead.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells", "generic": 3, "increase": True,
                "except_caster_own_turn": True,
            })],
        ),
    ]


register("Defense Grid", _defense_grid)

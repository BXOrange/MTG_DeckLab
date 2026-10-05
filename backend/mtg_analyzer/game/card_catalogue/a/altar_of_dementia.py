from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _altar_of_dementia() -> list[AbilitySpec]:
    """Sacrifice a creature: Target player mills cards equal to the
    sacrificed creature's power.

    — MEC-43. Needed the power sibling of `GameObject.sacrificed_cost_
    mana_value` (`sacrificed_cost_power`, now stamped by `GameEngine.
    _pay_ability_cost` alongside the mana-value one) and a new `MillEffect.
    count_selector` param reading it back via `continuous.count_selector`'s
    matching new entry.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {
                "target_kind": "player", "count_selector": "sacrificed_cost_power",
            })],
            cost={"sacrifice": "creature"},
        ),
    ]


register("Altar of Dementia", _altar_of_dementia)

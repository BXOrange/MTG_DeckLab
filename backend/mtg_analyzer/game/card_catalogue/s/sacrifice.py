from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sacrifice() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add an amount of {B} equal to the sacrificed creature's mana value.

    — MEC-43. Burnt Offering's fixed-colour sibling: `AddManaEffect`'s
    existing ``color``/``amount_selector`` variable-count form (the same
    shape Mana Drain already used), reading `sacrificed_cost_mana_value`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "B", "amount_selector": "sacrificed_cost_mana_value"})],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Sacrifice", _sacrifice)

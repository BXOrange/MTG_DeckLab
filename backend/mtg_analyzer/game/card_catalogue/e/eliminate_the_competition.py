from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eliminate_the_competition() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice X creatures.
    Destroy X target creatures.

    X, targets and sacrifices are announced and paid while casting.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("destroy", {
        "target_kind": "creature", "count": 100, "count_selector": "source_x_paid",
    })], additional_cost={"sacrifice_count": [-1, "creature"]})]


register("Eliminate the Competition", _eliminate_the_competition)

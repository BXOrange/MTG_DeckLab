from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _immoral_bargain() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice X creatures.
    Destroy X target nonland permanents."""
    return [AbilitySpec("spell_effect", [EffectSpec("destroy", {
        "target_kind": "nonland_permanent", "count": 100, "count_selector": "source_x_paid",
    })], additional_cost={"sacrifice_count": [-1, "creature"]})]


register("Immoral Bargain", _immoral_bargain)

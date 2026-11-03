from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_sculpt() -> list[AbilitySpec]:
    """Counter target spell. If you control a Wizard, add an amount of {C} equal to the amount of mana spent to cast that spell at the beginning of your next main phase."""
    return [AbilitySpec("spell_effect", [EffectSpec("counter_then_delayed_spent_mana", {})])]


register("Mana Sculpt", _mana_sculpt)

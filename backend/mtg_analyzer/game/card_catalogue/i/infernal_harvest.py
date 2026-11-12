"""Infernal Harvest."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _infernal_harvest():
    """As an additional cost to cast this spell, return X Swamps you control to their owner's hand.
Infernal Harvest deals X damage divided as you choose among any number of target creatures.
"""
    return [AbilitySpec("spell_effect", [EffectSpec("damage", {
        "amount": 0, "x_multiplier": 1, "target_kind": "creature", "count_selector": "source_x_paid",
        "optional": True, "divided": True, "division_required": True,
    })], additional_cost={"return_pick": ["x", "swamp"]})]


register("Infernal Harvest", _infernal_harvest)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chain_reaction() -> list[AbilitySpec]:
    """Chain Reaction deals X damage to each creature, where X is the
    number of creatures on the battlefield."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 0, "selector": "each_creature",
                "amount_from_count_selector": "all_creatures",
            })],
        )
    ]


register("Chain Reaction", _chain_reaction)

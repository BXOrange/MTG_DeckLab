from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _power_artifact() -> list[AbilitySpec]:
    """Enchant artifact
    Enchanted artifact's activated abilities cost {2} less to activate.
    This effect can't reduce the mana in that cost to less than one mana.

    — Power Artifact. A new activation-cost-reduction primitive
    (`continuous.activation_cost_reduction_for`/`GameEngine.
    _reduced_activation_mana`) — unlike a spell's cast cost
    (`cost_reduction_for`), nothing in the ordinary activation-cost path
    consulted a reduction before this. ``scope="activation"`` distinguishes
    it from the ordinary spell-cost `cost_reduction` shape sharing the same
    "cost" layer; ``min_total=1`` is the printed floor.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "attached_permanent", "generic": 2,
                "scope": "activation", "min_total": 1,
            })],
        )
    ]


register("Power Artifact", _power_artifact)

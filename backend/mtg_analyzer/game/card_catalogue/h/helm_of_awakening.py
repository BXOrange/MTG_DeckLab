from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _helm_of_awakening() -> list[AbilitySpec]:
    """Spells cost {1} less to cast.

    — Helm of Awakening. Unscoped (``affects="all_spells"``, not the
    default ``"your_spells"``) — `continuous.cost_reduction_for` never
    gates ``"all_spells"`` by controller at all (the same shape Thalia,
    Guardian of Thraben's tax uses in reverse), so every player's spells
    get the discount, this permanent's own controller included.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"affects": "all_spells", "generic": 1})],
        )
    ]


register("Helm of Awakening", _helm_of_awakening)

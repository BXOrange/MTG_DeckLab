from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blasphemous_act() -> list[AbilitySpec]:
    """This spell costs {1} less to cast for each creature on the
    battlefield.
    Blasphemous Act deals 13 damage to each creature.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. The cost reduction is `cost_reduction`'s existing
    Delve/Affinity-shaped ``per`` count-selector param, just with the new
    unscoped `creatures_on_battlefield` selector instead of the `_you_
    control`-scoped form every existing consumer used.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1, "per": "creatures_on_battlefield",
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 13, "selector": "each_creature"})],
        ),
    ]


register("Blasphemous Act", _blasphemous_act)

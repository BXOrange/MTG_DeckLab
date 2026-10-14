from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bone_shaman() -> list[AbilitySpec]:
    """{B}: Until end of turn, this creature gains "Creatures dealt damage by this creature this turn can't be
    regenerated this turn."

    PAR-109. The granted ability is a continuous effect with no stack object of its own, so granting it is the same as
    marking the source: `deny_regen_to_damaged` sets `temp_deny_regen_to_damaged` (RULE 701.16), which
    `RulesEngine.destroy` consults for every creature this source damaged this turn, before or after the activation.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("deny_regen_to_damaged", {})],
            cost={"mana": "{B}"},
        ),
    ]


register("Bone Shaman", _bone_shaman)

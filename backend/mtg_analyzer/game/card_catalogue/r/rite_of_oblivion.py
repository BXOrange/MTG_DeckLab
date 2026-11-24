from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rite_of_oblivion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a nonland permanent.
    Exile target nonland permanent.
    Flashback {2}{W}{B} (You may cast this card from your graveyard for its flashback cost and any additional costs. Then exile it.)
    """
    return [AbilitySpec(
        "spell_effect",
        [EffectSpec("exile", {"target_kind": "nonland_permanent"})],
        additional_cost={"sacrifice": "nonland_permanent"},
    )]


register("Rite of Oblivion", _rite_of_oblivion)

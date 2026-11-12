from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _noise_marine() -> list[AbilitySpec]:
    """Cascade (When you cast this spell, exile cards from the top of your library until you exile a nonland card that costs less. You may cast it without paying its mana cost. Put the exiled cards on the bottom in a random order.)
    Sonic Blaster — When this creature enters, it deals damage equal to the number of spells you've cast this turn to any target.
    """
    return [AbilitySpec("triggered", [EffectSpec("damage", {
        "amount_from_count_selector": "spells_cast_this_turn", "target_kind": "any",
    })], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}})]


register("Noise Marine", _noise_marine)

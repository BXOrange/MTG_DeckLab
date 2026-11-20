from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fireblast() -> list[AbilitySpec]:
    """You may sacrifice two Mountains rather than pay this spell's mana
    cost.
    Fireblast deals 4 damage to any target.

    — Imodane deck batch. The damage clause already parses on its own --
    reproduced verbatim. The alternative cost (RULE 118.9) is the
    `alt_cost` ``sacrifice_count`` key: the caster names the two Mountains
    (ENG-65, `cast_alt_cost_payment`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        ),
        AbilitySpec("spell_effect", [], alt_cost={"sacrifice_count": [2, "mountain"]}),
    ]


register("Fireblast", _fireblast)

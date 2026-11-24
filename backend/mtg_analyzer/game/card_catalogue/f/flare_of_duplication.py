from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flare_of_duplication() -> list[AbilitySpec]:
    """You may sacrifice a nontoken red creature rather than pay this spell's
    mana cost. Copy target instant or sorcery spell. You may choose new
    targets for the copy.

    — Flare of Duplication. The copy effect is the `copy_spell` primitive;
    the alternative cost (RULE 118.9) is `alt_cost`'s ``sacrifice_filter``
    key (a nontoken red creature, the caster's pick -- ENG-65).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
        ),
        AbilitySpec(
            "spell_effect", [],
            alt_cost={"sacrifice_filter": {"card_type": "creature", "color": "R", "nontoken": True}},
        ),
    ]


register("Flare of Duplication", _flare_of_duplication)

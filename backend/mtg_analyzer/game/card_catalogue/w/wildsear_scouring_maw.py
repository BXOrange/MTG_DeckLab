from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wildsear_scouring_maw() -> list[AbilitySpec]:
    """Trample
    Enchantment spells you cast from your hand have cascade. (Whenever you cast an enchantment
    spell from your hand, exile cards from the top of your library until you exile a nonland card
    that costs less. You may cast it without paying its mana cost. Put the exiled cards on the
    bottom in a random order.)

    — Animated Army deck batch. Trample is a keyword. The grant is the Rain of Riches shape
    (`grant_keyword` on ``spells_you_cast``, read by `continuous.granted_cast_keyword_instances`)
    with two new filters, ``card_types`` and ``from_hand``.
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "spells_you_cast", "keywords": ["cascade"],
            "card_types": ["enchantment"], "from_hand": True,
        })]),
    ]


register("Wildsear, Scouring Maw", _wildsear_scouring_maw)

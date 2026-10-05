from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Abstract Performance (two piles, opponent splits) — PAR-60
# ===========================================================================
# New `abstract_performance` effect. Documented simplification: "an opponent
# chooses one of those piles" is auto-resolved (the higher-total-MV pile
# goes to your graveyard); from the kept pile the highest-MV non-land card
# gets a this-turn free-cast window, the rest go to your hand.


def _abstract_performance() -> list[AbilitySpec]:
    """Exile the top four cards of your library in a face-down pile, then
    exile the top four cards of your library in a face-up pile. An opponent
    chooses one of those piles. Put that pile into your graveyard. Look at
    the cards in the other pile. You may cast a spell from among them
    without paying its mana cost. Put the rest into your hand."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("abstract_performance", {})],
        ),
    ]


register("Abstract Performance", _abstract_performance)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gamble() -> list[AbilitySpec]:
    """Search your library for a card, put that card into your hand,
    discard a card at random, then shuffle.

    RULE 701.8d: the discard is random (`DiscardEffect(random=True)`), no
    chooser; the tutored card is already in hand, so it can be the one lost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": "", "destination": "hand"}),
                EffectSpec("discard", {"count": 1, "random": True}),
            ],
        ),
    ]


register("Gamble", _gamble)

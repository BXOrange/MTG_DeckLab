from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gamble() -> list[AbilitySpec]:
    """Search your library for a card, put that card into your hand,
    discard a card at random, then shuffle.

    — Imodane deck batch. **Documented simplification**: "at random"
    becomes an ordinary discard choice — the same simplification
    Indoraptor, the Perfect Hybrid's own "choose an opponent at random"
    already established in this catalogue (a real choice instead of
    randomness has no rules-relevant difference an MVP needs to model).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": "", "destination": "hand"}),
                EffectSpec("discard", {"count": 1}),
            ],
        ),
    ]


register("Gamble", _gamble)

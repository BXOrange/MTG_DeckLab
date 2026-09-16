from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demonic_bargain() -> list[AbilitySpec]:
    """Demonic Bargain (Sorcery, {2}{B})

    "Exile the top thirteen cards of your library, then search your
    library for a card. Put that card into your hand, then shuffle."

    `ExileTopOfLibraryEffect`'s ``count`` param (MEC-43 round 4C, widened
    from its original top-**one**-card-only shape) for the first clause;
    the search itself is the plain, already-generic `SearchLibraryEffect`
    — its own "then shuffle" always fires (RULE 701.19e), over whatever
    thirteen fewer cards remain after the exile.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile_top_of_library", {"count": 13}),
                EffectSpec("search", {"criteria": {}, "destination": "hand"}),
            ],
        )
    ]


register("Demonic Bargain", _demonic_bargain)

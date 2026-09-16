from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unmarked_grave() -> list[AbilitySpec]:
    """Search your library for a nonlegendary card, put that card into
    your graveyard, then shuffle.

    — MEC-43. Plain `SearchLibraryEffect(destination="graveyard")`; only
    needed a new ``"nonlegendary": True`` key in the search-criteria
    vocabulary (`models/card_query.py`), the negation of the already-
    supported "legendary" type-line word.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {"criteria": {"nonlegendary": True}, "destination": "graveyard"})],
        ),
    ]


register("Unmarked Grave", _unmarked_grave)

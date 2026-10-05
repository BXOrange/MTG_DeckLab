from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _captain_sisay() -> list[AbilitySpec]:
    """{T}: Search your library for a legendary card, reveal that card, put it
    into your hand, then shuffle.

    — PLAY-ALL Step 2 (SpongeBob). The `search` for a card with a type-line
    word, here the supertype "Legendary" (`card_query` matches the word in the
    type line, the same ``criteria.type`` shape Goblin Matron uses for a
    subtype), to ``hand``; the tap is the ability's cost.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {"criteria": {"type": "Legendary"}, "destination": "hand"})],
            cost={"text": "{T}"},
        ),
    ]


register("Captain Sisay", _captain_sisay)

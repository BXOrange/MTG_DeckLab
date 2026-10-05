from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _phyrexian_incubator() -> list[AbilitySpec]:
    """{3}, {T}, Sacrifice Phyrexian Incubator: Search your library for any
    number of Phyrexian cards or cards with phyrexian back faces, exile
    them, then incubate 2 that many times. Then shuffle.

    — "incubate 2 **that many times**", where "that many" is the count of
    cards the search exiled, across the RULE 608.2 pending-choice
    suspension the search opens. Solved without a `GameContext`
    accumulator: `SearchLibraryEffect(track_exiled_with=True)` appends each
    exiled card to the source's own `GameObject.exiled_with_ids` (the same
    list `ExileEffect.track_exiled_with` writes), which lives on the
    permanent and so survives the suspend/resume; the following
    `create_token` reads it back with ``count_selector="exiled_with_count"``
    (Abdel Adrian's own "for each permanent exiled this way" selector).
    "Then shuffle" is `_finish_search`'s default (library zone, no
    exile_rest).

    **Documented simplification**: "or cards with phyrexian back faces" is
    dropped — `card_query`'s type-line substring match claims "Phyrexian
    cards" (the Phyrexian subtype) but not a DFC whose *back* face is
    Phyrexian while the front isn't; no such card is in a normal library
    search target for this artifact's real decks.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Phyrexian"},
                    "count": 99,  # "any number of" — the shared search sentinel
                    "optional": True,
                    "destination": "exile",
                    "track_exiled_with": True,
                }),
                EffectSpec("create_token", {
                    "token_name": "Incubator",
                    "count_selector": "exiled_with_count",
                    "extra_counters": {"kind": "+1/+1", "count": 2},
                }),
            ],
            cost={"text": "{3}, {T}, Sacrifice ~"},
        ),
    ]


register("Phyrexian Incubator", _phyrexian_incubator)

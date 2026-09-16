from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tibalts_trickery() -> list[AbilitySpec]:
    """Counter target spell. Choose 1, 2, or 3 at random. Its controller
    mills that many cards, then exiles cards from the top of their library
    until they exile a nonland card with a different name than that spell.
    They may cast that card without paying its mana cost. Then they put the
    exiled cards on the bottom of their library in a random order.

    — Tibalt's Trickery. One atomic `ScrambleSpellEffect`, shared with
    Possibility Storm below: both answer a spell and then dig **its
    controller's** library for a replacement they may cast free, differing
    only in how the spell is answered and what the dig looks for. A
    composition of separate counter/mill/dig effects couldn't work — every
    clause is about the same spell and the same (not-the-caster) player, and
    the dig's predicate is derived from that spell's own name via the new
    ``not_name`` criteria key (`models.cards.card_query`), the negated form of an
    exact name match, kept as its own key rather than a magic value inside
    ``name`` so a criteria dict stays literal data.

    **Documented simplifications**, both about hidden information the
    goldfish/replay model has no place for yet: "choose 1, 2, or 3 at
    random" is resolved by the engine rather than by a secret simultaneous
    number choice (there is no hidden-information channel between players),
    and "they may cast that card" is taken automatically — the free cast is
    the only reason anyone resolves this. Tracked in
    `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scramble_spell", {
                "answer": "counter",
                "match": "different_name",
                "mill_random_max": 3,
            })],
        ),
    ]


register("Tibalt's Trickery", _tibalts_trickery)

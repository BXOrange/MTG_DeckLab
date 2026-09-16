from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dark_petition() -> list[AbilitySpec]:
    """Dark Petition (Sorcery, {3}{B}{B})

    "Search your library for a card, put that card into your hand, then
    shuffle.
    Spell mastery — If there are two or more instant and/or sorcery cards
    in your graveyard, add {B}{B}{B}."

    The search half is already parser-``MODELED`` as-is (`author_card.py
    reuse`); hand-authored anyway so Spell mastery's own conditional bonus
    mana rides alongside it in one entry, the same "flat effect + a
    conditional extra one" shape Cabal Ritual's Threshold already uses.
    `EffectSpec.condition`'s new ``instant_sorcery_cards_in_graveyard_at_
    least`` key (MEC-43 round 4C) is `cards_in_graveyard_at_least`'s
    type-filtered sibling, reusing `continuous.count_selector`'s already-
    shipped ``"instant_sorcery_or_adventure_cards_in_your_graveyard"``
    entry instead of re-deriving the type filter.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": {}, "destination": "hand"}),
                EffectSpec(
                    "add_mana", {"colors": ["B", "B", "B"]},
                    condition={"instant_sorcery_cards_in_graveyard_at_least": 2},
                ),
            ],
        )
    ]


register("Dark Petition", _dark_petition)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eye_of_ugin() -> list[AbilitySpec]:
    """Colorless Eldrazi spells you cast cost {2} less to cast.
    {7}, {T}: Search your library for a colorless creature card, reveal
    it, put it into your hand, then shuffle.

    — MEC-12 (sixth pass). The search half is left to the oracle-text
    parser (`_SEARCH_COLOR_WORD`'s new "colorless" entry, matched onto
    `models.cards.card_query`'s own colour-emptiness check) rather than
    duplicated here — only the static half is hand-authored, since a
    combined colour-emptiness-**and**-creature-subtype cost filter
    ("Colorless Eldrazi spells", as opposed to a bare colour or a bare
    main-card-type filter) is this pass's own new primitive
    (`continuous.cost_reduction_for`'s `spell_color="colorless"` +
    `spell_subtype="Eldrazi"`, composed by plain AND) with no other real
    card on this exact combined shape yet — not worth a general "<colour-
    or-colorless> <optional creature subtype> spells [you cast] cost {N}
    less" grammar until a second one does. Both abilities are hand-
    authored on the same registered card regardless, since a registered
    card's catalogue entry replaces the parser's own output wholesale
    rather than merging with it — the search line below is simply the
    identical shape the parser would already produce for this card on
    its own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "spell_color": "colorless", "spell_subtype": "Eldrazi",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "colorless"},
                "destination": "hand",
            })],
            cost={"text": "{7}, {T}"},
        ),
    ]


register("Eye of Ugin", _eye_of_ugin)

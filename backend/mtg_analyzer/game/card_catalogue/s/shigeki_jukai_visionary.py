from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shigeki_jukai_visionary() -> list[AbilitySpec]:
    """{1}{G}, {T}, Return Shigeki to its owner's hand: Reveal the top four cards of your library. You may put a land
    card from among them onto the battlefield tapped. Put the rest into your graveyard.
    Channel — {X}{X}{G}{G}, Discard this card: Return X target nonlegendary cards from your graveyard to your hand.

    — PLAY-ALL Step 2 (Sultai Arisen). The first ability is the parser's own claim, reproduced. The second is
    activated from the hand (``discard_self`` cost, like cycling) and targets exactly X nonlegendary cards (the new
    ``nonlegendary_card`` graveyard filter) through ``count_selector="source_x_paid"`` — the same announced-X target
    count `Death Denied` uses (PAR-30).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("inspect_top_choose", {
                "count": 4, "action": "library_to_battlefield_tapped", "max_picks": 1, "optional": True,
                "criteria": {"type": "land"}, "rest_destination": "graveyard",
            })],
            cost={"text": "{1}{g}, {t}, return ~ to its owner's hand"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonlegendary_card", "destination": "hand",
                "count_selector": "source_x_paid", "optional": True,
            })],
            cost={"text": "{x}{x}{g}{g}, discard this card"},
        ),
    ]


register("Shigeki, Jukai Visionary", _shigeki_jukai_visionary)

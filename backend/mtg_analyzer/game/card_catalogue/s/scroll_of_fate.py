from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scroll_of_fate() -> list[AbilitySpec]:
    """{T}: Manifest a card from your hand. (Put that card onto the battlefield face down as a 2/2 creature. Turn it face up any time for its mana cost if it's a creature card.)

    — PLAY-ALL (Jump Scare!). A `choose_objects` over your hand with the new ``manifest_from_hand`` action: the pick is turned
    face down before it enters (RULE 708.3, so its own abilities never trigger) and put onto the battlefield. An empty
    hand does nothing; a single card is taken without asking.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("choose_objects", {
                "action": "manifest_from_hand", "what": "permanent", "pool_zones": ["hand"], "count": 1,
                "prompt": "Karte aus der Hand verdeckt ausspielen (Manifest)",
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Scroll of Fate", _scroll_of_fate)

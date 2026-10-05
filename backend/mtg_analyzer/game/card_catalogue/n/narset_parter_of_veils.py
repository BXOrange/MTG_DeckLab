from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _narset_parter_of_veils() -> list[AbilitySpec]:
    """Each opponent can't draw more than one card each turn.
    −2: Look at the top four cards of your library. You may reveal a
    noncreature, nonland card from among them and put it into your hand.
    Put the rest on the bottom of your library in a random order.

    — MEC-12 (cEDH M-K). The static is `draw_limit`'s new ``affects``
    param (default was hardwired to ``"all"``, Spirit-of-the-Labyrinth-
    shaped) — see `continuous.max_draws_per_turn`'s own docstring. The
    loyalty ability is `impulsive_look` with the new ``without_type``
    `card_query` key (`"creature"`/`"land"`, AND-combined — RULE 205's
    main types only) and the new ``miss_destination="library_bottom_
    random"`` (a *group* shuffle of the un-revealed cards, not each one
    independently bottomed in reveal order).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"affects": "opponents", "max_per_turn": 1})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 4, "criteria": {"without_type": ["creature", "land"]},
                "hit_destination": "hand", "miss_destination": "library_bottom_random",
                "optional": True,
            })],
            cost={"loyalty": -2},
        ),
    ]


register("Narset, Parter of Veils", _narset_parter_of_veils)

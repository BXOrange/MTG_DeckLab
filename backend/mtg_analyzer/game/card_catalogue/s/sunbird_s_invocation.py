from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sunbirds_invocation() -> list[AbilitySpec]:
    """Whenever you cast a spell from your hand, reveal the top X cards of
    your library, where X is that spell's mana value. You may cast a
    spell with mana value X or less from among cards revealed this way
    without paying its mana cost. Put the rest on the bottom of your
    library in a random order.

    — Imodane deck batch. **Documented simplification**: modeled as
    revealing and offering a free cast of only the *top card* of the
    library (not the top X, and without the "mana value X or less"
    filter) — `dig_until`'s existing "reveal until a match, free-cast the
    hit, shuffle/bottom the rest" shape (Tibalt's Trickery/Possibility
    Storm-shaped), reused with an always-true criteria so it stops at
    exactly one card. A criteria keyed to X (the triggering spell's mana
    value) was tried and reverted: `dig_until` reveals cards *until* one
    matches, so on a low X and an unlucky top of library it would dig
    arbitrarily deep — safe for Tibalt's Trickery (nothing shares its
    exact name) but wrong here, where most of a deck's cards have a
    higher mana value than a cheap spell's X. The real card's "look at X
    cards, pick any one of them, mana-value-gated" breadth isn't modeled
    — a genuinely different chooser shape (`dig_until` stops at the first
    match rather than surveying a fixed window) that would need its own
    primitive.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": "",
                "hit_destination": "cast_free_window",
                "rest_destination": "exile",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"from_hand": True},
            },
        ),
    ]


register("Sunbird's Invocation", _sunbirds_invocation)

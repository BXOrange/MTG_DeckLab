from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _professor_onyx() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    each opponent loses 2 life and you gain 2 life.
    +1: You lose 1 life. Look at the top three cards of your library. Put
    one of them into your hand and the rest into your graveyard.
    −3: Each opponent sacrifices a creature with the greatest power among
    creatures that player controls.
    −8: Each opponent may discard a card. If they don't, they lose 3 life.
    Repeat this process six more times.

    — Professor Onyx. Magecraft already parsed; the three loyalty abilities
    are hand-authored here.

    The −3 needed one narrow extension: `SacrificeEffect` gained
    ``greatest_power``, because this is the one place the engine's
    non-interactive "first matching permanent" auto-pick would be actively
    *wrong* rather than merely uninteresting — the card's whole effect is
    that the sacrificing player can't dodge with a spare token. It also
    gained an ``each_opponent`` selector and a registry entry (it had only
    ever been reachable from the annihilator keyword).

    **Documented simplification**: the −8's "each opponent may discard a
    card. If they don't, they lose 3 life. Repeat six more times." is
    modeled as seven rounds of a straight discard-or-lose-3, resolved
    non-interactively (discard if able, else lose the life) rather than as
    seven interactive `pay_cost_then` prompts per opponent — the outcome is
    identical for any opponent with cards, and an empty-handed one loses the
    life either way. Tracked in `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("lose_life", {"amount": 1, "player": "controller"}),
                EffectSpec("impulsive_look", {
                    "count": 3, "criteria": "", "hit_destination": "hand",
                    "miss_destination": "graveyard", "optional": False,
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {
                "count": 1, "what": "creature",
                "selector": "each_opponent", "greatest_power": True,
            })],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("discard_or_lose_life", {
                "count": 1, "amount": 3, "times": 7, "selector": "each_opponent",
            })],
            cost={"loyalty": -8},
        ),
    ]


register("Professor Onyx", _professor_onyx)

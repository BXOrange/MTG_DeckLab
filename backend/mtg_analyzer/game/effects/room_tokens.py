"""RULE 709.5 / 707.2: "Choose a Room card at random. Create a token that's a copy of one of its halves, then unlock it."
(Blu, Mansion Prince.)

The Room pool is the cached, paper-legal Room cards (an Alchemy Room is a permanent non-goal); the card is drawn with the
game-state-seeded RNG (RULE 706) so the draw survives clone/undo. Which half the token copies is the controller's choice
(`RoomsRulesMixin._resume_room_half_choice`).
"""
from __future__ import annotations

from typing import Any, Optional

from .core import EffectRegistry, GameEffect, GameContext, _controller_of
from ...models.cards.card import Card

#: The Room cards eligible for the random pick, by canonical name (sorted so a seeded draw is reproducible). Built lazily
#: once per process: scanning the whole card cache costs under a second but must not run on every trigger.
_ROOM_POOL: Optional[list[str]] = None


def room_pool() -> list[str]:
    """Names of every paper Room card in the card cache (RULE 709.5: a split card whose shared type line is a Room)."""
    global _ROOM_POOL
    if _ROOM_POOL is None:
        from ...services.card_lookup import default_card_database
        from ..rooms import has_doors

        _ROOM_POOL = sorted(
            card.name for card in default_card_database().list_cards()
            if has_doors(card) and not card.digital
        )
    return _ROOM_POOL


def room_half_options(card: Card) -> list[dict[str, str]]:
    """The two halves of ``card`` as choice options, keyed by the door designation they correspond to."""
    from ..rooms import DOORS, door_name

    return [{"id": door, "label": door_name(card, door)} for door in DOORS]


class RandomRoomHalfTokenEffect(GameEffect):
    """Pick a Room card at random, then let the controller choose the half the token copies."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.card_lookup import card_by_name

        controller = _controller_of(self.source, context)
        pool = room_pool()
        if controller is None or not pool:
            return  # RULE 608.2b: with no Room card to choose, do as much as possible (nothing)
        name = pool[context.engine.random_int(len(pool))]
        card = card_by_name(name)
        if card is None:
            return
        context.engine._request_room_half_choice(controller, card)


EffectRegistry.register("random_room_half_token", lambda p: RandomRoomHalfTokenEffect())

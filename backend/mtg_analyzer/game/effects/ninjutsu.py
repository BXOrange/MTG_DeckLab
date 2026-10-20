"""Ninjutsu's resolution half (RULE 702.49a).

The costs of a ninjutsu activation (mana, reveal, return the unblocked
attacker) are paid in `GameEngine.ninjutsu`; this effect is what sits on the
stack and, on resolution, puts the Ninja onto the battlefield tapped and
attacking. It stores ids and a plain defender dict (never object references)
so a `state.clone()` taken for undo keeps it intact.
"""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from .core import GameContext, GameEffect


class NinjutsuEffect(GameEffect):
    """RULE 702.49a: "Put this card onto the battlefield from your hand
    tapped and attacking."

    ``defender`` is the defender the returned creature was attacking,
    captured at activation (RULE 702.49d: the Ninja attacks the same player,
    planeswalker or battle). ``ninja_incarnation`` pins the exact visit of
    the card to the hand (RULE 400.7): a Ninja that left the hand in
    response is a new object and the ability does nothing (RULE 608.2b-ish
    "can't be found" handling for a vanished source).
    """

    def __init__(
        self, ninja_id: int, owner_id: str, ninja_incarnation: int,
        defender: Optional[dict[str, Any]],
    ) -> None:
        super().__init__(None)
        self.ninja_id = ninja_id
        self.owner_id = owner_id
        self.ninja_incarnation = ninja_incarnation
        self.defender = dict(defender) if defender else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        state = context.state
        ninja = state.find_object(self.ninja_id)
        owner = state.player_by_id(self.owner_id)
        if (
            ninja is None or owner is None or ninja not in owner.hand
            or ninja.zone_incarnation != self.ninja_incarnation
        ):
            return  # RULE 400.7: no longer in hand -> nothing to put onto the battlefield
        owner.remove_from_zone(ninja, Zone.HAND)
        # RULE 702.49a / 508.4: enters tapped and attacking, never declared as
        # an attacker, so summoning sickness is irrelevant and no attack triggers.
        ninja.tapped = True
        ninja.summoning_sick = False
        state.add_to_battlefield(ninja)
        context.engine.put_onto_battlefield_attacking(ninja, defender=self.defender)
        state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD, controller_id=ninja.controller_id,
                from_zone=Zone.HAND.value,
                card_id=ninja.card.id, object=ninja.name, instance_id=ninja.instance_id,
                object_types=sorted(ninja.type_words),
            )
        )

"""Rooms: locking and unlocking doors by an instruction (RULE 709.5f/709.5g, MEC-111).

The designation machinery is `game/rooms.py`; this is the part that needs a *player's choice* — "unlock a locked
door of a Room you control" names no particular door, so with more than one candidate the controller picks.
"""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from .. import continuations, rooms

#: The two things an instruction can do to a door (RULE 709.5f / 709.5g).
UNLOCK = "unlock"
LOCK = "lock"


class RoomsRulesMixin:
    def _door_options(self, rooms_in_play: list[GameObject], *, can_lock: bool) -> list[tuple[str, GameObject, str]]:
        """Every ``(action, room, door)`` an instruction may take: a locked door can be unlocked and, when the
        instruction also locks ("lock or unlock a door"), an unlocked door can be locked."""
        options: list[tuple[str, GameObject, str]] = []
        for room in rooms_in_play:
            if room.zone != Zone.BATTLEFIELD or not rooms.has_doors(room.card):
                continue
            options.extend((UNLOCK, room, door) for door in rooms.locked_doors(room))
            if can_lock:
                options.extend((LOCK, room, door) for door in rooms.DOORS if door in room.unlocked_doors)
        return options

    def _apply_door_option(self, action: str, room: GameObject, door: str) -> bool:
        """Do one chosen `door_options` entry."""
        if action == LOCK:
            return rooms.lock(self.state, room, door)
        return rooms.unlock(self.state, room, door)

    def _request_door_choice(self, player: Player, options: list[tuple[str, GameObject, str]]) -> None:
        """Ask ``player`` which door to act on; `_resume_door_choice` applies the answer."""
        self.open_choice({
            "kind": "door_choice",
            "player_id": player.id,
            "prompt": "Welche Tür?",
            "options": [
                {
                    "id": f"{action}:{room.instance_id}:{door}",
                    "label": f"{room.name}: {rooms.door_name(room.card, door)} "
                             f"{'entriegeln' if action == UNLOCK else 'verriegeln'}",
                }
                for action, room, door in options
            ],
        })

    def _request_room_half_choice(self, player: Player, room_card: Any) -> None:
        """Ask ``player`` which half of the randomly chosen Room card their token copies (Blu, Mansion Prince)."""
        from ..effects.room_tokens import room_half_options

        self.open_choice({
            "kind": "room_half_choice",
            "player_id": player.id,
            "prompt": f"{room_card.name}: welche Hälfte kopieren?",
            "room_name": room_card.name,
            "options": room_half_options(room_card),
        })

    @continuations.choice("room_half_choice", answer=continuations.ANSWER_STR, rule="707.2")
    def _resume_room_half_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Create the token copy of the chosen half, then unlock it (RULE 709.5f).

        Documented simplification: a token copy of one half has a single door, which is not modelled as a locked/unlocked
        designation (``rooms.has_doors`` is false for it); its abilities are bound at creation and the unlock is the
        ``DOOR_UNLOCKED`` event (RULE 709.5h), so "when you unlock this door" abilities of that half still trigger."""
        from ...services.card_lookup import card_by_name
        from ...models.game.events import EventType, GameEvent

        card = card_by_name(choice["room_name"])
        ids = [str(option["id"]) for option in choice["options"]]
        door = answer if answer in ids else ids[0]
        half = rooms.door_card(card, door) if card is not None else None
        if half is None:
            return

        def unlock_token(tokens: list[GameObject]) -> None:
            from ..binding.core import attach_to_object  # function-scoped: the binder imports the registry

            for token in tokens:
                # `bind_from_catalogue` binds a Room only through its designations, which the one-door token has
                # none of: give it the half's abilities (door-scoped, as `rooms.bind_door` does) before the unlock.
                attach_to_object(token, rooms.door_specs(card, door))
                self.state.fire_event(GameEvent(
                    EventType.DOOR_UNLOCKED, instance_id=token.instance_id, controller_id=token.controller_id,
                    player_id=token.controller_id, object=token.name, object_types=sorted(token.type_words),
                    door=door, door_name=half.name,
                ))

        self.create_token(choice["player_id"], half, 1, on_created=unlock_token)

    @continuations.choice("door_choice", answer=continuations.ANSWER_STR, rule="709.5f")
    def _resume_door_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `door_choice` — mandatory, so a missing/invalid answer takes the first option."""
        ids = [str(option["id"]) for option in choice["options"]]
        picked = answer if answer in ids else ids[0]
        action, instance_id, door = picked.split(":")
        room = self._object_by_instance_id(int(instance_id))
        if room is not None:
            self._apply_door_option(action, room, door)

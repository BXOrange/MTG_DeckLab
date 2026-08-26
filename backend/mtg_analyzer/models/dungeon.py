"""Dungeons (RULE 309) — a card type that never touches a deck.

A dungeon card "begins outside the game" (RULE 309.2), is brought in by the
venture-into-the-dungeon keyword action (RULE 701.49), sits in its owner's
command zone while it's being explored (309.2b), is never a permanent and
can't be cast (309.2c). What a player actually does with it is move a
**venture marker** down a directed graph of *rooms*: each room has a name
(flavour only, 309.4b) and one triggered ability — "When you move your
venture marker into this room, [effect]" (309.4c) — and one or more arrows
to the rooms that may follow it (309.5a).

Modeled as plain data on the player (`Player.dungeon`), not as a
`GameObject`: a dungeon has no characteristics a permanent has (no
power/toughness, no controller-vs-owner split, no zone changes but the one
that removes it from the game), and every "leaves the battlefield"/"is
targeted"/layer-engine path a `GameObject` drags along would be dead weight.
That is the same reasoning `models/emblem.py` gives, and `Emblem` was the
closest thing here before this module — deliberately a one-off, not a base
class, so the two stay independent.

`game/dungeons.py` parses a real dungeon card's printed text into these
structures and binds each room's effect; `RulesEngine.venture_into_the_dungeon`
moves the marker.
"""

from __future__ import annotations

from typing import Any, Optional


class DungeonRoom:
    """One room of a dungeon card (RULE 309.4).

    ``effect_text`` is the printed effect half of the room's line — the body
    of its room ability (309.4c). ``leads_to`` are the names of the rooms an
    arrow points to; an empty list marks a **bottommost** room (309.5b), the
    one whose ability completing the dungeon hangs off.
    """

    def __init__(self, name: str, effect_text: str, leads_to: Optional[list[str]] = None) -> None:
        self.name = name
        self.effect_text = effect_text
        self.leads_to: list[str] = list(leads_to or [])

    @property
    def is_last(self) -> bool:
        """RULE 309.5b: a room with no arrow leaving it is the bottommost one."""
        return not self.leads_to

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "effect_text": self.effect_text,
            "leads_to": list(self.leads_to),
        }

    def __repr__(self) -> str:
        return f"DungeonRoom({self.name!r}, leads_to={self.leads_to!r})"


class Dungeon:
    """One dungeon card in a player's command zone (RULE 309.2b), plus that
    player's venture marker (RULE 309.4).

    ``current_room`` is the room name the marker sits on, or ``None`` for a
    dungeon not yet entered (which only exists transiently — RULE 309.4a puts
    the marker on the topmost room as the card enters the command zone).
    ``restricted`` is Undercity's own "You can't enter this dungeon unless you
    'venture into Undercity'" clause: such a dungeon is kept out of the
    ordinary RULE 309.2a choice and only reachable by the RULE 701.49d
    "venture into [quality]" variant.
    """

    def __init__(
        self,
        name: str,
        rooms: list[DungeonRoom],
        card_id: str = "",
        image_uri: str = "",
        restricted: bool = False,
    ) -> None:
        self.name = name
        self.rooms = rooms
        self.card_id = card_id
        self.image_uri = image_uri
        self.restricted = restricted
        self.current_room: Optional[str] = None
        #: RULE 309.4c: "each room ability is controlled by the player who
        #: owns the dungeon card that is that ability's source" — so the
        #: dungeon *is* the source those abilities bind against, and carries
        #: the two fields the effect system reads off any source
        #: (`controller_id` for "you", `timestamp` for RULE 613.7b ordering),
        #: exactly as `models/emblem.py` does for a RULE 114 emblem. Set when
        #: the card is put into a command zone.
        self.controller_id: str = ""
        self.owner_id: str = ""
        self.timestamp: int = 0

    # -- Room graph ------------------------------------------------------

    def room(self, name: Optional[str]) -> Optional[DungeonRoom]:
        if name is None:
            return None
        return next((r for r in self.rooms if r.name == name), None)

    @property
    def top_room(self) -> Optional[DungeonRoom]:
        """RULE 309.4a: the topmost room — where a venture marker starts."""
        return self.rooms[0] if self.rooms else None

    @property
    def marker_room(self) -> Optional[DungeonRoom]:
        return self.room(self.current_room)

    def next_rooms(self) -> list[DungeonRoom]:
        """RULE 309.5a: the rooms an arrow leads to from the marker's room —
        empty on the bottommost room (RULE 309.5b/701.49c handle that case)."""
        room = self.marker_room
        if room is None:
            return []
        return [r for r in (self.room(n) for n in room.leads_to) if r is not None]

    @property
    def on_last_room(self) -> bool:
        room = self.marker_room
        return room is not None and room.is_last

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "card_id": self.card_id,
            "image_uri": self.image_uri,
            "current_room": self.current_room,
            "restricted": self.restricted,
            "rooms": [room.to_dict() for room in self.rooms],
        }

    def __repr__(self) -> str:
        return f"Dungeon({self.name!r}, marker={self.current_room!r})"

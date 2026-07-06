"""Player state: life, mana pool, zones (RULE 102, RULE 103, RULE 400).

Reference: docs/02_MVP_USECASES_REVISED.md R1.3 (Player State — Life,
Mana Pool, Priority, "is Active Player?"), docs/07_GAME_LOOP_EFFECT_SYSTEM.md.

A player owns the private/personal zones (library, hand, graveyard,
exile, command zone) plus the objects they control on the shared
battlefield. This model holds *state and primitive moves only* — drawing
mechanically takes cards off the library, but the replacement-effect and
triggered-ability consequences of a draw are the rules engine's job
(mtg_analyzer/game/), keeping the model layer free of rules logic so the
engine stays the single place rules live.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from .game_object import GameObject, Zone
from .mana_pool import ManaPool

#: Starting life for Commander/EDH (RULE 903.7).
DEFAULT_STARTING_LIFE = 40


class Player:
    """One player's game state and the zones they own."""

    #: Personal zones this player owns (the battlefield is shared and
    #: lives on GameState; command zone holds the commander).
    PERSONAL_ZONES = (Zone.LIBRARY, Zone.HAND, Zone.GRAVEYARD, Zone.EXILE, Zone.COMMAND)

    def __init__(
        self,
        id: str,
        name: str = "",
        life: int = DEFAULT_STARTING_LIFE,
    ) -> None:
        self.id = id
        self.name = name or id
        self.life = life
        self.mana_pool = ManaPool()

        #: Personal zones, each an ordered list of GameObjects. For the
        #: library, the *end* of the list is the top of the deck (draws
        #: pop from the end), so shuffling and dealing are cheap.
        self.zones: dict[Zone, list[GameObject]] = {zone: [] for zone in self.PERSONAL_ZONES}

        #: Per-turn flags, reset by the engine at the start of each turn.
        self.lands_played_this_turn = 0
        self.max_lands_per_turn = 1

        #: Whether this player has lost (RULE 104.3). Kept distinct from
        #: removal from the game so history/UI can show the reason.
        self.has_lost = False
        self.loss_reason: Optional[str] = None

        #: Effects that live on the player rather than a permanent —
        #: e.g. "skip your next untap step", "you can't lose the game".
        #: The rules engine reads these; see game/effects.py.
        self.player_effects: list[Any] = []

    # -- Zone accessors --------------------------------------------------

    @property
    def library(self) -> list[GameObject]:
        return self.zones[Zone.LIBRARY]

    @property
    def hand(self) -> list[GameObject]:
        return self.zones[Zone.HAND]

    @property
    def graveyard(self) -> list[GameObject]:
        return self.zones[Zone.GRAVEYARD]

    @property
    def exile(self) -> list[GameObject]:
        return self.zones[Zone.EXILE]

    @property
    def command(self) -> list[GameObject]:
        return self.zones[Zone.COMMAND]

    # -- Primitive moves (no rules consequences; engine orchestrates) ----

    def add_to_zone(self, obj: GameObject, zone: Zone) -> None:
        """Place ``obj`` into one of this player's personal zones."""
        if zone not in self.zones:
            raise ValueError(f"{zone} is not a personal zone")
        obj.zone = zone
        self.zones[zone].append(obj)

    def remove_from_zone(self, obj: GameObject, zone: Zone) -> None:
        self.zones[zone].remove(obj)

    def shuffle_library(self) -> None:
        """Randomize the order of this player's library (RULE 701.20).

        A primitive move like `draw`: it changes zone contents but fires no
        event itself — the rules engine wraps this to announce a ``SHUFFLE``
        (so a "whenever a player shuffles" trigger can see it) and to keep
        library-searching (RULE 701.19e "then shuffle") in one place.
        """
        random.shuffle(self.library)

    def draw(self, count: int = 1) -> list[GameObject]:
        """Move up to ``count`` cards from the top of the library to hand.

        Returns the cards actually drawn. Drawing from an empty library
        does not itself lose the game here — that is a state-based action
        the rules engine checks (RULE 104.3c / 704.5c).
        """
        drawn: list[GameObject] = []
        for _ in range(count):
            if not self.library:
                break
            card = self.library.pop()  # top of deck
            card.zone = Zone.HAND
            self.hand.append(card)
            drawn.append(card)
        return drawn

    def lose_life(self, amount: int) -> None:
        self.life -= amount

    def gain_life(self, amount: int) -> None:
        self.life += amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "life": self.life,
            "mana_pool": self.mana_pool.to_dict(),
            "has_lost": self.has_lost,
            "loss_reason": self.loss_reason,
            "library_count": len(self.library),
            "hand": [obj.to_dict() for obj in self.hand],
            "graveyard": [obj.to_dict() for obj in self.graveyard],
            "exile": [obj.to_dict() for obj in self.exile],
            "command": [obj.to_dict() for obj in self.command],
        }

    def __repr__(self) -> str:
        return f"Player(id={self.id!r}, life={self.life}, hand={len(self.hand)}, library={len(self.library)})"

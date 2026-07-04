"""Zones and in-game card instances (RULE 400 zones, RULE 110 permanents).

Reference: docs/02_MVP_USECASES_REVISED.md R1.3 (Game State — Zones,
Stack, permanents), docs/07_GAME_LOOP_EFFECT_SYSTEM.md.

A `Card` (models/card.py) is the immutable *definition* of a card — its
printed characteristics. A `GameObject` is one *instance* of that card
inside a running game: a specific object in a specific zone with its own
mutable state (tapped, damage, counters, summoning sickness) and its own
identity, so two copies of the same card, or the same physical card seen
in two zones over time, stay distinguishable. This mirrors the rules'
distinction between a card and the object it becomes in play.
"""

from __future__ import annotations

import itertools
from enum import Enum
from typing import Any, Optional

from .card import Card


class Zone(str, Enum):
    """The zones a game object can occupy (RULE 400)."""

    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    STACK = "stack"
    EXILE = "exile"
    COMMAND = "command"


#: Process-wide counter giving every GameObject a unique instance id.
_instance_counter = itertools.count(1)


class GameObject:
    """One instance of a card in a game, with its mutable in-play state."""

    def __init__(
        self,
        card: Card,
        owner_id: str,
        zone: Zone = Zone.LIBRARY,
        controller_id: Optional[str] = None,
    ) -> None:
        self.instance_id: int = next(_instance_counter)
        self.card = card
        self.owner_id = owner_id
        #: Who currently controls the object; defaults to its owner
        #: (RULE 108.4). Control can change but ownership can't.
        self.controller_id = controller_id or owner_id
        self.zone = zone

        # Permanent state (meaningful on the battlefield).
        self.tapped: bool = False
        #: Summoning sickness (RULE 302.6): a creature can't attack/tap
        #: until its controller has controlled it since their last turn
        #: began. Set when it enters, cleared at that controller's untap.
        self.summoning_sick: bool = True
        #: Damage marked this turn (RULE 120); cleared during cleanup.
        self.damage_marked: int = 0
        #: +1/+1 (positive) and -1/-1 (negative) counters, net.
        self.plus_one_counters: int = 0

        #: Effects this object contributes while in play, consulted by the
        #: rules engine (mtg_analyzer/game/). Typed loosely to avoid a
        #: model→game import; they hold `GameEffect` subclasses.
        self.triggered_abilities: list[Any] = []
        self.replacement_effects: list[Any] = []
        self.static_effects: list[Any] = []
        self.activated_abilities: list[Any] = []

    # -- Delegated characteristics (read from the printed card) ---------

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def is_creature(self) -> bool:
        return self.card.is_creature

    @property
    def is_land(self) -> bool:
        return self.card.is_land

    @property
    def is_legendary(self) -> bool:
        return self.card.is_legendary

    @property
    def power(self) -> Optional[int]:
        """Effective power including counters, or None for non-creatures."""
        if self.card.power is None:
            return None
        return self.card.power + self.plus_one_counters

    @property
    def toughness(self) -> Optional[int]:
        """Effective toughness including counters, or None for non-creatures."""
        if self.card.toughness is None:
            return None
        return self.card.toughness + self.plus_one_counters

    # -- State transitions ----------------------------------------------

    def tap(self) -> None:
        self.tapped = True

    def untap(self) -> None:
        self.tapped = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the instance's game state (for the wire protocol)."""
        return {
            "instance_id": self.instance_id,
            "card_id": self.card.id,
            "name": self.card.name,
            "owner_id": self.owner_id,
            "controller_id": self.controller_id,
            "zone": self.zone.value,
            "tapped": self.tapped,
            "summoning_sick": self.summoning_sick,
            "damage_marked": self.damage_marked,
            "power": self.power,
            "toughness": self.toughness,
        }

    def __repr__(self) -> str:
        return f"GameObject(#{self.instance_id} {self.card.name!r} in {self.zone.value})"

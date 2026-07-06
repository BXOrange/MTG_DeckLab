"""GameState: the whole shared game (RULE 100, RULE 400 shared zones).

Reference: docs/02_MVP_USECASES_REVISED.md R1.3 (Game State), R4.1 (Game
Loop), docs/07_GAME_LOOP_EFFECT_SYSTEM.md.

This is the single source of truth for a game in progress: the players,
the shared battlefield/stack, whose turn it is, which phase/step we're
in, and who holds priority. It is deliberately *data + an event bus*, not
rules: it records events and notifies subscribers (the rules engine
subscribes to turn events into triggers), but it doesn't decide what
events mean. That keeps every rule in one place — the engine — while
GameState stays serializable for the WebSocket wire protocol.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Callable, Optional

from .events import GameEvent
from .game_object import GameObject, Zone
from .player import Player


class StackItem:
    """One spell or ability on the stack (RULE 405, RULE 608).

    ``kind`` is ``"spell"`` or ``"ability"``; ``obj`` is the spell's game
    object (None for an ability that isn't a card); ``effects`` are the
    `GameEffect`s applied when it resolves; ``controller_id`` is who put
    it on the stack; ``targets`` records chosen targets; ``x`` is the
    value announced for a cost containing ``{X}`` (RULE 601.2b), 0
    otherwise.

    ``category`` is the finer classification the UI shows so a player can
    tell *what kind of thing* is waiting on the stack — one of ``"spell"``,
    ``"triggered_ability"``, or ``"activated_ability"`` (RULE 601 / 602 /
    603). When not given it is derived from the effect on the stack by
    class name, which keeps this model free of a `game/` import.
    """

    def __init__(
        self,
        kind: str,
        controller_id: str,
        effects: Optional[list[Any]] = None,
        obj: Optional[GameObject] = None,
        description: str = "",
        targets: Optional[list[Any]] = None,
        x: int = 0,
        category: Optional[str] = None,
    ) -> None:
        self.kind = kind
        self.controller_id = controller_id
        self.effects = effects or []
        self.obj = obj
        self.description = description
        self.targets = targets or []
        self.x = x
        self.category = category or self._derive_category()

    def _derive_category(self) -> str:
        """Classify the item for display without importing `game/` types.

        Spells are known from ``kind``; an ability is triggered or
        activated depending on the effect object it carries, matched by
        class name so this stays a pure model (see `GameObject`).
        """
        if self.kind == "spell":
            return "spell"
        for effect in self.effects:
            name = type(effect).__name__
            if name == "ActivatedAbility":
                return "activated_ability"
            if name == "TriggeredAbility":
                return "triggered_ability"
        # The only ability path wired into gameplay today is triggered.
        return "triggered_ability"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "category": self.category,
            "controller_id": self.controller_id,
            "description": self.description or (self.obj.name if self.obj else ""),
            "object": self.obj.to_dict() if self.obj else None,
            "type_line": self.obj.card.type_line if self.obj else "",
            "x": self.x,
        }

    def __repr__(self) -> str:
        label = self.description or (self.obj.name if self.obj else self.kind)
        return f"StackItem({self.kind} {label!r})"


class GameState:
    """The full state of one game and a light event bus over it."""

    def __init__(self, players: list[Player], id: Optional[str] = None) -> None:
        if not players:
            raise ValueError("a game needs at least one player")
        self.id = id or str(uuid.uuid4())
        self.players = players

        self.turn_number = 0
        self.active_player_index = 0
        #: Which player currently holds priority (RULE 117); None between
        #: priority windows (e.g. during untap).
        self.priority_player_index: Optional[int] = None
        self.current_phase: str = ""
        self.current_step: str = ""

        #: The shared battlefield (RULE 403) and the stack (RULE 405).
        self.battlefield: list[GameObject] = []
        self.stack: list[StackItem] = []

        self.game_over = False
        self.winner_id: Optional[str] = None

        #: A player decision the engine is waiting on (e.g. a library
        #: search) before it can keep resolving — plain JSON-able data
        #: (kind, player_id, eligible instance ids, …) so it survives a
        #: `clone()` for rewind and serializes to the UI. None when the
        #: engine isn't blocked on a choice. Set/consumed by the rules
        #: engine (mtg_analyzer/game/rules_engine.py).
        self.pending_choice: Optional[dict[str, Any]] = None

        #: Chronological log of everything fired; also the record the
        #: WebSocket layer can diff to build ``game_state_update``s.
        self.event_log: list[GameEvent] = []
        #: Observer callbacks invoked for every fired event.
        self._subscribers: list[Callable[[GameEvent], None]] = []

    # -- Players ---------------------------------------------------------

    @property
    def active_player(self) -> Player:
        return self.players[self.active_player_index]

    @property
    def priority_player(self) -> Optional[Player]:
        if self.priority_player_index is None:
            return None
        return self.players[self.priority_player_index]

    def player_by_id(self, player_id: str) -> Player:
        for player in self.players:
            if player.id == player_id:
                return player
        raise KeyError(f"no player with id {player_id!r}")

    def find_object(self, instance_id: int) -> Optional[GameObject]:
        """Locate a game object by its instance id across every zone.

        Lets an action referencing an object by id (as `legal_actions`
        reports it) be resolved back to the live `GameObject`, which is
        essential after a rewind swaps in a fresh copy of the state.
        """
        for obj in self.battlefield:
            if obj.instance_id == instance_id:
                return obj
        for item in self.stack:
            if item.obj is not None and item.obj.instance_id == instance_id:
                return item.obj
        for player in self.players:
            for zone in player.zones.values():
                for obj in zone:
                    if obj.instance_id == instance_id:
                        return obj
        return None

    def non_active_players(self) -> list[Player]:
        return [p for i, p in enumerate(self.players) if i != self.active_player_index]

    def living_players(self) -> list[Player]:
        return [p for p in self.players if not p.has_lost]

    # -- Battlefield -----------------------------------------------------

    def permanents(self) -> list[GameObject]:
        """Every object on the shared battlefield."""
        return list(self.battlefield)

    def permanents_controlled_by(self, player_id: str) -> list[GameObject]:
        return [obj for obj in self.battlefield if obj.controller_id == player_id]

    def add_to_battlefield(self, obj: GameObject) -> None:
        obj.zone = Zone.BATTLEFIELD
        self.battlefield.append(obj)

    def remove_from_battlefield(self, obj: GameObject) -> None:
        if obj in self.battlefield:
            self.battlefield.remove(obj)

    # -- Event bus -------------------------------------------------------

    def subscribe(self, callback: Callable[[GameEvent], None]) -> None:
        """Register a callback fired for every event (e.g. trigger collection)."""
        self._subscribers.append(callback)

    def clone(self) -> "GameState":
        """A deep, self-contained copy of the game — for undo/restart.

        Event subscribers (bound methods of a live `RulesEngine`) and the
        event log are intentionally *not* copied: the clone is inert game
        data, and whoever restores it wraps a fresh engine around it that
        re-subscribes. Because the underlying `Card` definitions are
        immutable and share via ``Card.__deepcopy__``, and `GameObject`
        instance ids are plain values, all in-state references (an object
        on the battlefield vs. referenced from the stack) stay consistent
        across the copy.
        """
        subscribers, log = self._subscribers, self.event_log
        self._subscribers, self.event_log = [], []
        try:
            clone = copy.deepcopy(self)
        finally:
            self._subscribers, self.event_log = subscribers, log
        return clone

    def fire_event(self, event: GameEvent) -> GameEvent:
        """Record ``event`` and notify subscribers. Returns the event.

        This is deliberately consequence-free beyond notification —
        replacement effects are applied by the engine *before* it calls
        ``fire_event`` (the event here is what actually happened), and
        triggered abilities are queued by subscribers.
        """
        self.event_log.append(event)
        for subscriber in list(self._subscribers):
            subscriber(event)
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turn_number": self.turn_number,
            "active_player_id": self.active_player.id,
            "priority_player_id": self.priority_player.id if self.priority_player else None,
            "current_phase": self.current_phase,
            "current_step": self.current_step,
            "game_over": self.game_over,
            "winner_id": self.winner_id,
            "pending_choice": self.pending_choice,
            "players": [p.to_dict() for p in self.players],
            "battlefield": [obj.to_dict() for obj in self.battlefield],
            "stack": [item.to_dict() for item in self.stack],
        }

    def __repr__(self) -> str:
        return (
            f"GameState(id={self.id!r}, turn={self.turn_number}, "
            f"active={self.active_player.id!r}, step={self.current_step!r})"
        )

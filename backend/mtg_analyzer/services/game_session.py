"""Server-held game sessions: goldfish (with rewind/restart) + multiplayer stub.

Reference: docs/02_MVP_USECASES_REVISED.md UC3 (Goldfisch) / UC4
(Multiplayer), backend/ToDo_Backend.md "Game Engine".

A `GameSession` wraps a `GameEngine` and adds what a *test-your-deck*
session needs on top of the pure rules engine:

* **Restart** — reset to the exact opening state at any time (UC3).
* **Rewind** — undo the last move(s). Implemented as a stack of full
  `GameState.clone()` snapshots taken before each action, so undo is
  exact (it restores real game state, not a replay that could diverge)
  and works for any action including auto-played turns.

Actions arrive as plain dicts in the same shape `GameEngine.legal_actions`
reports, so the UI can round-trip "here are your options → I pick this
one" without a translation layer.

`GameSessionManager` holds sessions in memory keyed by id (like
`game_ws.py`'s connection manager — single process, not persisted).
Multiplayer is a deliberate stub (`MultiplayerNotImplementedError`): the
session type is modeled so the API surface exists, but interactive
two-player priority isn't wired yet (see ToDo "Multiplayer game session").
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.game_engine import GameEngine

#: How many undo snapshots to retain (older moves drop off the bottom).
MAX_HISTORY = 100

GOLDFISH = "goldfish"
MULTIPLAYER = "multiplayer"


class GameActionError(Exception):
    """An action was illegal or malformed for the current game state."""


class MultiplayerNotImplementedError(Exception):
    """Interactive multiplayer isn't built yet — see ToDo 'Multiplayer'."""


def build_goldfish_engine(
    library: list[Card],
    commanders: Optional[list[Card]] = None,
    player_name: str = "You",
    starting_life: int = 40,
    starting_hand: int = 7,
) -> GameEngine:
    """Build a solo `GameEngine` and deal an opening hand (UC3).

    The 99 non-commander cards become the library (as given — the caller
    shuffles first if they want randomness, so tests stay deterministic);
    commanders start in the command zone (RULE 903.6). Casting from the
    command zone isn't wired yet, so for now the commander is visible but
    not yet playable — the deck's own cards are what a goldfish tests.
    """
    player = Player(id="p1", name=player_name, life=starting_life)
    for card in library:
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    for card in commanders or []:
        player.add_to_zone(GameObject(card, owner_id="p1", zone=Zone.COMMAND), Zone.COMMAND)

    state = GameState(players=[player])
    engine = GameEngine(state)
    player.draw(starting_hand)
    engine.start()
    return engine


class GameSession:
    """A running game with undo history and restart."""

    def __init__(
        self, engine: GameEngine, mode: str = GOLDFISH, session_id: Optional[str] = None
    ) -> None:
        self.id = session_id or str(uuid.uuid4())
        self.mode = mode
        self.engine = engine
        #: Pristine opening state + step position, so restart is exact.
        self._initial: tuple[GameState, int] = (engine.state.clone(), engine.step_cursor)
        #: (label, pre-action snapshot, cursor) stack; rewind pops the end.
        #: The step cursor lives on the engine, not the state, so it must
        #: travel with each snapshot or a mid-turn undo would jump turns.
        self._history: list[tuple[str, GameState, int]] = []
        #: Human-readable labels of applied actions, for the UI.
        self.move_log: list[str] = []

    # -- Snapshot / restore --------------------------------------------

    def _snapshot(self, label: str) -> None:
        self._history.append((label, self.engine.state.clone(), self.engine.step_cursor))
        if len(self._history) > MAX_HISTORY:
            self._history.pop(0)

    def _restore(self, state: GameState, cursor: int) -> None:
        # A fresh engine re-subscribes its rules to the restored state;
        # seek it back to where the turn was.
        self.engine = GameEngine(state.clone())
        self.engine.resume_at(cursor)

    @property
    def can_rewind(self) -> bool:
        return bool(self._history)

    def restart(self) -> dict[str, Any]:
        """Reset to the opening state (UC3: 'jederzeit neu starten')."""
        state, cursor = self._initial
        self._restore(state, cursor)
        self._history.clear()
        self.move_log.clear()
        return self.view()

    def rewind(self, steps: int = 1) -> dict[str, Any]:
        """Undo the last ``steps`` moves. Undoing more than exist restarts."""
        if steps < 1:
            raise GameActionError("rewind steps must be >= 1")
        state: Optional[GameState] = None
        cursor = 0
        for _ in range(steps):
            if not self._history:
                return self.restart()
            _label, state, cursor = self._history.pop()
            if self.move_log:
                self.move_log.pop()
        assert state is not None
        self._restore(state, cursor)
        return self.view()

    # -- Actions -------------------------------------------------------

    def apply_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Validate + apply one action, snapshotting first so it can be undone.

        Raises `GameActionError` for anything illegal, leaving the game
        untouched (the pre-action snapshot is restored on failure).
        """
        if not isinstance(action, dict) or "type" not in action:
            raise GameActionError("action must be a dict with a 'type'")
        label = self._describe(action)
        self._snapshot(label)
        try:
            self._dispatch(action)
        except (ValueError, KeyError) as exc:
            # Roll back the failed attempt so state stays clean.
            _, snapshot, cursor = self._history.pop()
            self._restore(snapshot, cursor)
            raise GameActionError(str(exc)) from exc
        self.move_log.append(label)
        return self.view()

    def _dispatch(self, action: dict[str, Any]) -> None:
        state = self.engine.state
        active = state.active_player
        kind = action["type"]

        if kind in ("advance_step", "advance", "next_step", "pass_priority"):
            if kind == "pass_priority":
                # No opponent to hold priority: passing resolves the stack.
                self.engine.resolve_until_stable()
            else:
                self.engine.advance_step()
            return

        if kind == "auto_turn":
            self._auto_turn()
            return

        if kind == "play_land":
            self.engine.play_land(active, self._object(action))
            self.engine.resolve_until_stable()
            return

        if kind == "tap_for_mana":
            self.engine.tap_for_mana(active, self._object(action))
            return

        if kind == "cast_spell":
            targets = self._resolve_targets(action.get("targets"))
            self.engine.cast_spell(active, self._object(action), targets)
            self.engine.resolve_until_stable()
            return

        if kind in ("attack", "declare_attackers"):
            ids = action.get("instance_ids")
            if ids is None and "instance_id" in action:
                ids = [action["instance_id"]]
            attackers = [self._object_by_id(i) for i in (ids or [])]
            self.engine.declare_attackers(active, attackers)
            return

        raise GameActionError(f"unknown action type: {kind!r}")

    def _auto_turn(self) -> None:
        """Finish the current turn on autopilot, respecting the step cursor.

        Drives ``advance_step`` (not ``run_goldfish_turn``, which would
        ``begin_turn`` behind the cursor's back and desync a game the
        player has been stepping through), auto-playing the goldfish line
        at each step, and stops once the next turn begins.
        """
        start_turn = self.engine.state.turn_number
        for _ in range(60):  # generous per-turn step cap; guards runaway loops
            if self.engine.state.game_over:
                return
            self.engine.auto_play_step()
            if self.engine.advance_step() is None:
                return
            if self.engine.state.turn_number != start_turn:
                return

    def _object(self, action: dict[str, Any]) -> GameObject:
        if "instance_id" not in action:
            raise GameActionError(f"{action['type']} needs an instance_id")
        return self._object_by_id(action["instance_id"])

    def _object_by_id(self, instance_id: Any) -> GameObject:
        obj = self.engine.state.find_object(int(instance_id))
        if obj is None:
            raise GameActionError(f"no game object with instance_id {instance_id!r}")
        return obj

    def _resolve_targets(self, targets: Optional[list[Any]]) -> Optional[list[Any]]:
        if not targets:
            return None
        resolved: list[Any] = []
        for target in targets:
            if isinstance(target, dict) and "player_id" in target:
                resolved.append(self.engine.state.player_by_id(target["player_id"]))
            elif isinstance(target, dict) and "instance_id" in target:
                resolved.append(self._object_by_id(target["instance_id"]))
            else:
                resolved.append(target)
        return resolved

    @staticmethod
    def _describe(action: dict[str, Any]) -> str:
        name = action.get("name")
        kind = action["type"]
        return f"{kind}: {name}" if name else kind

    # -- Views ---------------------------------------------------------

    def legal_actions(self) -> list[dict[str, Any]]:
        return self.engine.legal_actions(self.engine.state.active_player)

    def view(self) -> dict[str, Any]:
        """Everything the UI needs to render the session after a change."""
        return {
            "session_id": self.id,
            "mode": self.mode,
            "state": self.engine.state.to_dict(),
            "legal_actions": self.legal_actions(),
            "can_rewind": self.can_rewind,
            "move_log": list(self.move_log),
        }


class GameSessionManager:
    """In-memory registry of active game sessions (single process)."""

    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}

    def create_goldfish(
        self,
        library: list[Card],
        commanders: Optional[list[Card]] = None,
        player_name: str = "You",
        starting_life: int = 40,
        starting_hand: int = 7,
    ) -> GameSession:
        engine = build_goldfish_engine(
            library, commanders, player_name, starting_life, starting_hand
        )
        session = GameSession(engine, mode=GOLDFISH)
        self._sessions[session.id] = session
        return session

    def create_multiplayer(self, *args: Any, **kwargs: Any) -> GameSession:
        """Stub: interactive multiplayer isn't implemented yet (UC4).

        Modeled so the API/route exists and returns a clear, typed
        "not yet" rather than a 404, but there is no interactive priority
        loop — see backend/ToDo_Backend.md "Multiplayer game session".
        """
        raise MultiplayerNotImplementedError(
            "Multiplayer mode is not implemented yet; use goldfish mode."
        )

    def get(self, session_id: str) -> GameSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def remove(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

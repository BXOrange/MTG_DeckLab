"""Server-held game sessions: goldfish (with rewind/restart) + multiplayer stub.

Reference: docs/02_MVP_USECASES_REVISED.md UC3 (Goldfisch) / UC4
(Multiplayer), backend/Done_Backend.md "Game Engine".

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

#: Safety cap on "advance_step"'s auto-skip loop (docs/02 R4.1) so a
#: board with genuinely nothing to do for many turns (e.g. mana screw)
#: can't hang the request; generous relative to ~11 steps/turn.
_MAX_AUTO_ADVANCE_STEPS = 200

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
    commanders start in the command zone (RULE 903.6) and can be cast
    from there (`GameEngine.can_cast`); commander tax (RULE 903.8) isn't
    modeled yet.
    """
    player = Player(id="p1", name=player_name, life=starting_life)
    for card in library:
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    for card in commanders or []:
        obj = GameObject(card, owner_id="p1", zone=Zone.COMMAND, is_commander=True)
        player.add_to_zone(obj, Zone.COMMAND)

    state = GameState(players=[player])
    engine = GameEngine(state)
    player.draw(starting_hand)
    engine.start()
    return engine


class GameSession:
    """A running game with undo history and restart."""

    def __init__(
        self,
        engine: GameEngine,
        mode: str = GOLDFISH,
        session_id: Optional[str] = None,
        starting_hand: int = 7,
        require_setup: bool = False,
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

        #: Whether a mulligan/keep-hand setup phase gates play (only real
        #: goldfish sessions from `GameSessionManager.create_goldfish` set
        #: this — tests that build a `GameSession` directly to exercise the
        #: turn loop keep the old no-setup behaviour unless they opt in).
        self._require_setup = require_setup
        self._starting_hand = starting_hand
        #: How many mulligans have been taken (London mulligan: each one
        #: redraws 7, then keeping puts that many cards on the bottom).
        self._mulligan_count = 0
        self._setup_complete = not require_setup

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
        self._mulligan_count = 0
        self._setup_complete = not self._require_setup
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

        # Setup phase (UC3: mulligan before the game proper starts): only
        # `mulligan`/`keep_hand` are legal until the opening hand is kept.
        if not self._setup_complete:
            if kind == "mulligan":
                self._mulligan(active)
                return
            if kind == "keep_hand":
                self._keep_hand(active, action.get("bottom_instance_ids") or [])
                return
            raise ValueError("finish the mulligan phase before playing")

        # While the engine is blocked on a choice (e.g. a library search),
        # only the choice may be answered.
        if state.pending_choice and kind not in ("choose", "decline"):
            raise GameActionError("a choice is pending — answer it first")

        if kind in ("choose", "decline"):
            instance_id = action.get("instance_id") if kind == "choose" else None
            self.engine.resolve_pending_choice(
                int(instance_id) if instance_id is not None else None
            )
            return

        if kind in ("advance_step", "advance", "next_step"):
            self._advance_with_auto_skip()
            return

        if kind == "pass_priority":
            # Pass priority once: resolve the top of the stack (RULE 117),
            # one object at a time so instants can be cast in response.
            self.engine.pass_priority()
            return

        if kind == "auto_turn":
            self._auto_turn()
            return

        if kind == "play_land":
            self.engine.play_land(active, self._object(action))
            return

        if kind == "tap_for_mana":
            option_index = int(action.get("option_index", 0))
            self.engine.tap_for_mana(active, self._object(action), option_index)
            return

        if kind == "cast_spell":
            # The spell goes on the stack; it does NOT auto-resolve, so the
            # player can respond (cast an instant) or pass priority to let
            # it resolve — real stack interaction (RULE 608).
            targets = self._resolve_targets(action.get("targets"))
            x = int(action.get("x", 0))
            self.engine.cast_spell(active, self._object(action), targets, x)
            return

        if kind in ("attack", "declare_attackers"):
            ids = action.get("instance_ids")
            if ids is None and "instance_id" in action:
                ids = [action["instance_id"]]
            attackers = [self._object_by_id(i) for i in (ids or [])]
            self.engine.declare_attackers(active, attackers)
            return

        raise GameActionError(f"unknown action type: {kind!r}")

    def _mulligan(self, player: Player) -> None:
        """London mulligan, part 1: shuffle the hand back and draw 7 (RULE 103.4-103.5)."""
        while player.hand:
            obj = player.hand.pop()
            obj.zone = Zone.LIBRARY
            player.library.append(obj)
        player.shuffle_library()
        player.draw(self._starting_hand)
        self._mulligan_count += 1

    def _keep_hand(self, player: Player, bottom_instance_ids: list[Any]) -> None:
        """London mulligan, part 2: keep, bottoming one card per mulligan taken."""
        if len(bottom_instance_ids) != self._mulligan_count:
            raise ValueError(
                f"must put exactly {self._mulligan_count} card(s) on the bottom of the library"
            )
        chosen: list[GameObject] = []
        for instance_id in bottom_instance_ids:
            obj = next((o for o in player.hand if o.instance_id == instance_id), None)
            if obj is None or obj in chosen:
                raise ValueError(f"card {instance_id!r} is not a valid bottom selection")
            chosen.append(obj)
        for obj in chosen:
            player.remove_from_zone(obj, Zone.HAND)
            obj.zone = Zone.LIBRARY
            player.library.insert(0, obj)  # bottom of library (index 0 — see Player.library)
        self._setup_complete = True

    def _advance_with_auto_skip(self) -> None:
        """Advance one step, then keep going while nothing is interactive.

        "Nächster Schritt" shouldn't force a click through every untap/
        upkeep/draw/cleanup step (and empty combat steps) when there's
        nothing to decide there — it stops at the first step offering a
        real choice (a castable/playable card, an eligible attacker, a
        pending choice, or a non-empty stack awaiting priority), same as
        if the player had clicked through the empty ones themselves.
        Mana abilities (`tap_for_mana`) don't count as "interactive" here:
        the mana pool empties at the end of every step anyway, so tapping
        during an otherwise-empty step has no effect worth stopping for.
        """
        for _ in range(_MAX_AUTO_ADVANCE_STEPS):
            if self.engine.advance_step() is None:
                return
            if self._step_has_interaction():
                return

    def _step_has_interaction(self) -> bool:
        state = self.engine.state
        if state.game_over or state.pending_choice or state.stack:
            return True
        interactive_types = {"play_land", "cast_spell", "attack"}
        return any(
            action["type"] in interactive_types
            for action in self.engine.legal_actions(state.active_player)
        )

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
        if not self._setup_complete:
            # `bottom_count` tells the UI how many cards `keep_hand` must
            # bottom this time (0 on the very first hand, before any
            # mulligan has been taken).
            return [
                {"type": "mulligan"},
                {"type": "keep_hand", "bottom_count": self._mulligan_count},
            ]
        pending = self.engine.state.pending_choice
        if pending:
            # A choice is pending: the only legal actions are answering it.
            actions = [
                {
                    "type": "choose",
                    "instance_id": entry["instance_id"],
                    "name": entry["name"],
                }
                for entry in pending.get("eligible", [])
            ]
            if pending.get("optional"):
                actions.append({"type": "decline"})
            return actions
        return self.engine.legal_actions(self.engine.state.active_player)

    def view(self) -> dict[str, Any]:
        """Everything the UI needs to render the session after a change."""
        return {
            "session_id": self.id,
            "mode": self.mode,
            "state": self.engine.state.to_dict(),
            "legal_actions": self.legal_actions(),
            "pending_choice": self.engine.state.pending_choice,
            "can_rewind": self.can_rewind,
            "move_log": list(self.move_log),
            "setup": {"complete": self._setup_complete, "mulligan_count": self._mulligan_count},
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
        session = GameSession(
            engine,
            mode=GOLDFISH,
            starting_hand=starting_hand,
            require_setup=True,
        )
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

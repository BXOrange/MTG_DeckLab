"""Server-held game sessions: goldfish (with rewind/restart) + multiplayer stub.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC3 (Goldfisch) / UC4
(Multiplayer), docs/implementation-state/Done_Backend.md "Game Engine".

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
from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.services import replay

#: How many undo snapshots to retain (older moves drop off the bottom).
MAX_HISTORY = 100

#: Safety cap on the "advance to next decision" skip loop so a board with
#: genuinely nothing to decide for many turns (e.g. mana screw) can't hang
#: the request; generous relative to ~11 steps/turn.
_MAX_DECISION_ADVANCE_STEPS = 200

GOLDFISH = "goldfish"
MULTIPLAYER = "multiplayer"
REPLAY = "replay"


class GameActionError(Exception):
    """An action was illegal or malformed for the current game state."""


class MultiplayerNotImplementedError(Exception):
    """Interactive multiplayer isn't built yet — see ToDo 'Multiplayer'."""


#: One shared filler card for the goldfish dummy's deck/hand. Its identity
#: never matters (the UI shows the dummy's hand face-down); it exists only so
#: discard/mill/forced-draw effects aimed at the goldfish have material to
#: move. A `Card` is an immutable definition safely shared across instances.
_DUMMY_FILLER = Card(id="goldfish-filler", name="Goldfisch-Karte", type_line="Card")

#: Cards in the passive opponent's library — generous so forced draws don't
#: deck it out during a normal test game (it never draws on its own turn).
_DUMMY_LIBRARY_SIZE = 60


def _build_dummy_player(starting_life: int, starting_hand: int) -> Player:
    """A passive "goldfish" opponent (UC3): a valid target for combat and for
    damage/discard/draw effects, with life and stats tracked, but one that
    never takes a turn or an action of its own."""
    dummy = Player(id="goldfish", name="Goldfisch", life=starting_life, is_dummy=True)
    for _ in range(_DUMMY_LIBRARY_SIZE):
        dummy.library.append(GameObject(_DUMMY_FILLER, owner_id="goldfish", zone=Zone.LIBRARY))
    dummy.draw(starting_hand)  # a hand to discard from; hidden in the UI
    return dummy


def build_goldfish_engine(
    library: list[Card],
    commanders: Optional[list[Card]] = None,
    player_name: str = "You",
    starting_life: int = 40,
    starting_hand: int = 7,
    with_dummy: bool = False,
) -> GameEngine:
    """Build a goldfish `GameEngine` and deal an opening hand (UC3).

    The 99 non-commander cards become the library (as given — the caller
    shuffles first if they want randomness, so tests stay deterministic);
    commanders start in the command zone (RULE 903.6) and can be cast
    from there (`GameEngine.can_cast`); commander tax (RULE 903.8) isn't
    modeled yet.

    With ``with_dummy`` a passive "Goldfisch" opponent is added (see
    `_build_dummy_player`) so attacks and discard/draw/damage effects have a
    target and both players' stats are tracked; the turn loop skips its turn.
    Off by default so the low-level builder stays a pure solo engine for
    tests that assert single-player behavior; `GameSessionManager.create_goldfish`
    turns it on for real games.
    """
    player = Player(id="p1", name=player_name, life=starting_life)
    for card in library:
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(obj)  # bind-on-load: card text → live abilities
        player.library.append(obj)
    for card in commanders or []:
        obj = GameObject(card, owner_id="p1", zone=Zone.COMMAND, is_commander=True)
        bind_from_catalogue(obj)
        player.add_to_zone(obj, Zone.COMMAND)

    players = [player]
    if with_dummy:
        players.append(_build_dummy_player(starting_life, starting_hand))

    state = GameState(players=players)
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
        #: A card loader for Replay-mode `edit_add_object` (resolving a card
        #: name → `Card` on the fly). Set by `create_replay`; None otherwise.
        self._loader: Any = None
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
        #: Turn-1 draw option (UC3): True → the human draws on their first
        #: turn ("on the draw"); False (default) → they skip it, the standard
        #: on-the-play rule. Chosen in the setup screen; applied at keep-hand.
        self._draw_first = False

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
        # "Next decision" is a fast-forward, but it must remain a sequence of
        # ordinary steps — each a real, separately snapshotted/logged
        # `advance_step` firing its own events — so the game evolves exactly
        # as clicking "Next step" would, and undo/replay stay deterministic
        # even with the opponent present. It manages its own history entries.
        if action["type"] in ("advance_to_decision", "next_decision"):
            return self._apply_advance_to_decision()
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

        # Replay/puzzle board editing (mode == REPLAY): direct state
        # mutations that bypass rules validation, so an arbitrary — even
        # rules-illegal — position can be constructed. Allowed at any time.
        if kind.startswith("edit_"):
            self._edit_dispatch(action)
            return

        # Setup phase (UC3: mulligan before the game proper starts): only
        # `mulligan`/`keep_hand` are legal until the opening hand is kept.
        if not self._setup_complete:
            if kind == "mulligan":
                self._mulligan(active)
                return
            if kind == "keep_hand":
                self._keep_hand(
                    active,
                    action.get("bottom_instance_ids") or [],
                    draw_first=action.get("draw_first"),
                )
                return
            if kind == "set_draw_first":
                # Toggle the turn-1 draw option during setup so the checkbox
                # stays in sync without committing the hand.
                self._draw_first = bool(action.get("value"))
                return
            raise ValueError("finish the mulligan phase before playing")

        # While the engine is blocked on a choice (e.g. a library search),
        # only the choice may be answered.
        if state.pending_choice and kind not in ("choose", "decline"):
            raise GameActionError("a choice is pending — answer it first")

        if kind in ("choose", "decline"):
            # A choice is answered by an option id ("cast"/"hand"/"decline" or
            # a card's instance id). `decline` is shorthand for the decline
            # option; a legacy `instance_id`-only payload still works.
            if kind == "decline":
                answer: Any = "decline"
            else:
                answer = action.get("option_id")
                if answer is None:
                    iid = action.get("instance_id")
                    answer = int(iid) if iid is not None else None
            self.engine.resolve_pending_choice(answer)
            return

        if kind in ("advance_step", "advance", "next_step"):
            # Advance exactly one step — no auto-skip, no auto-wait. The
            # player visits every step (untap, upkeep, draw, both mains, each
            # combat step, …) one click at a time.
            self.engine.advance_step()
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
            face = action.get("face", "front")
            self.engine.play_land(active, self._object(action), face=face)
            return

        if kind == "tap_for_mana":
            option_index = int(action.get("option_index", 0))
            ability_index = int(action.get("ability_index", 0))
            tap_choices = self._resolve_tap_choices(action.get("tap_choices"))
            self.engine.tap_for_mana(active, self._object(action), option_index, ability_index, tap_choices)
            return

        if kind == "cast_spell":
            # The spell goes on the stack; it does NOT auto-resolve, so the
            # player can respond (cast an instant) or pass priority to let
            # it resolve — real stack interaction (RULE 608).
            targets = self._resolve_targets(action.get("targets"))
            x = int(action.get("x", 0))
            face = action.get("face", "front")
            # RULE 700.2: a modal spell's chosen mode — an index into
            # `obj.spell_modes`, or "both" (RULE 700.2e) — round-trips from
            # the `mode` field `GameEngine._cast_action` stamped on the
            # offered action; absent for a non-modal spell.
            mode = action.get("mode")
            self.engine.cast_spell(active, self._object(action), targets, x, face=face, mode=mode)
            return

        if kind == "activate_ability":
            # Pay the ability's cost and put it on the stack (RULE 602); like a
            # spell it then waits for priority to resolve.
            targets = self._resolve_targets(action.get("targets"))
            x = int(action.get("x", 0))
            index = int(action.get("ability_index", 0))
            tap_choices = self._resolve_tap_choices(action.get("tap_choices"))
            self.engine.activate_ability(active, self._object(action), index, targets, x, tap_choices)
            return

        if kind in ("attack", "declare_attackers"):
            ids = action.get("instance_ids")
            if ids is None and "instance_id" in action:
                ids = [action["instance_id"]]
            # A single declared defender applies to every attacker in this
            # call (the UI declares one creature per click, each picking its
            # own defender). None → the engine auto-assigns / bare swing.
            defender = self._resolve_defender(action.get("defender"))
            declarations = [
                {"attacker": self._object_by_id(i), "defender": defender}
                for i in (ids or [])
            ]
            self.engine.declare_attackers(active, declarations)
            return

        if kind == "declare_blockers":
            # assignments: [{"blocker": id, "attacker": id}, ...], declared by
            # a defending player (dormant in solo goldfish — the dummy never
            # blocks). ``player_id`` names that defender; defaults to the
            # first non-active player.
            defender_id = action.get("player_id")
            blocker_player = (
                state.player_by_id(defender_id)
                if defender_id
                else next(iter(state.non_active_players()), None)
            )
            if blocker_player is None:
                raise GameActionError("no defending player to declare blockers")
            pairs = [
                {
                    "blocker": self._object_by_id(a["blocker"]),
                    "attacker": self._object_by_id(a["attacker"]),
                }
                for a in (action.get("assignments") or [])
            ]
            self.engine.declare_blockers(blocker_player, pairs)
            return

        raise GameActionError(f"unknown action type: {kind!r}")

    # -- Replay editing (mode == REPLAY) -------------------------

    def _edit_dispatch(self, action: dict[str, Any]) -> None:
        """Apply one board-editing action. Snapshotted/undoable by `apply_action`."""
        if self.mode != REPLAY:
            raise GameActionError("edit actions are only allowed in replay mode")
        kind = action["type"]
        state = self.engine.state

        if kind == "edit_add_object":
            self._edit_add_object(action)
        elif kind == "edit_remove_object":
            self._remove_object_everywhere(self._object(action))
        elif kind == "edit_move_object":
            self._edit_move_object(action)
        elif kind == "edit_reorder_object":
            self._edit_reorder_object(action)
        elif kind == "edit_set_flags":
            self._edit_set_flags(action)
        elif kind == "edit_transform":
            self.engine.rules.transform_permanent(self._object(action))
        elif kind == "edit_set_counters":
            self._set_counter_map(self._object(action).counters, action)
        elif kind == "edit_set_life":
            self._edit_player(action).life = int(action.get("value", 0))
        elif kind == "edit_set_poison":
            self._edit_player(action).poison = max(0, int(action.get("value", 0)))
        elif kind == "edit_set_mana":
            self._edit_set_mana(action)
        elif kind == "edit_set_player_counter":
            self._set_counter_map(self._edit_player(action).counters, action)
        elif kind == "edit_set_commander_damage":
            self._edit_commander_damage(action)
        elif kind == "edit_set_turn":
            self._edit_set_turn(action)
        else:
            raise GameActionError(f"unknown edit action: {kind!r}")

    def _edit_player(self, action: dict[str, Any]) -> Player:
        pid = action.get("player_id")
        if pid is None:
            raise GameActionError("edit action needs a player_id")
        try:
            return self.engine.state.player_by_id(str(pid))
        except KeyError as exc:
            raise GameActionError(f"no player with id {pid!r}") from exc

    @staticmethod
    def _set_counter_map(counters: dict[str, int], action: dict[str, Any]) -> None:
        """Set a named counter to an absolute ``amount`` (0 removes it)."""
        name = action.get("counter")
        if not name:
            raise GameActionError("counter edit needs a 'counter' name")
        amount = int(action.get("amount", 0))
        if amount > 0:
            counters[str(name)] = amount
        else:
            counters.pop(str(name), None)

    def _remove_object_everywhere(self, obj: GameObject) -> None:
        state = self.engine.state
        if obj in state.battlefield:
            state.remove_from_battlefield(obj)
            return
        for player in state.players:
            for objs in player.zones.values():
                if obj in objs:
                    objs.remove(obj)
                    return

    def _edit_add_object(self, action: dict[str, Any]) -> None:
        state = self.engine.state
        zone = Zone(action.get("zone", "battlefield"))
        owner_id = str(action.get("owner_id") or state.players[0].id)
        token = action.get("token")
        if token and zone != Zone.BATTLEFIELD:
            raise GameActionError(
                "a token can only be added to the battlefield — it ceases to "
                "exist in any other zone (RULE 111.7)"
            )
        inst: dict[str, Any] = {
            "name": action.get("name"),
            "card_id": action.get("card_id"),
            "is_token": bool(token),
            "token": token,
            "tapped": bool(action.get("tapped")),
            "summoning_sick": bool(action.get("summoning_sick", zone == Zone.BATTLEFIELD)),
            "counters": action.get("counters") or {},
            "is_commander": bool(action.get("is_commander")) or zone == Zone.COMMAND,
            "transformed": bool(action.get("transformed")),
        }
        cards_by_name: dict[str, Any] = {}
        if not inst["is_token"]:
            name = inst["name"]
            if not name:
                raise GameActionError("edit_add_object needs a card name or a token block")
            if self._loader is None:
                raise GameActionError("no card loader available for this session")
            cards_by_name = self._loader.load_cards([name]).cards
        controller = action.get("controller_id") if zone == Zone.BATTLEFIELD else None
        obj = replay.build_object(
            inst, owner_id=owner_id, cards_by_name=cards_by_name, controller_id=controller
        )
        if obj is None:
            raise GameActionError(f"could not resolve card {inst['name']!r}")
        if zone == Zone.BATTLEFIELD:
            obj.owner_id = owner_id
            obj.controller_id = str(action.get("controller_id") or owner_id)
            state.add_to_battlefield(obj)
        else:
            state.player_by_id(owner_id).add_to_zone(obj, zone)

    def _edit_move_object(self, action: dict[str, Any]) -> None:
        state = self.engine.state
        obj = self._object(action)
        target = Zone(action["zone"])
        if obj.is_token and target != Zone.BATTLEFIELD:
            raise GameActionError(
                "a token ceases to exist off the battlefield (RULE 111.7) — "
                "remove it instead of moving it there"
            )
        owner_id = str(action.get("owner_id") or obj.owner_id)
        self._remove_object_everywhere(obj)
        obj.owner_id = owner_id
        if target == Zone.BATTLEFIELD:
            obj.controller_id = str(action.get("controller_id") or owner_id)
            state.add_to_battlefield(obj)
        else:
            state.player_by_id(owner_id).add_to_zone(obj, target)

    def _edit_reorder_object(self, action: dict[str, Any]) -> None:
        """Swap ``instance_id`` with its neighbor one step toward the end of
        its zone's list (``direction: "up"``) or the start (``"down"``).

        Only meaningful for a personal zone's hidden order (RULE 401.1) —
        the library editor uses it to set draw order; the list is stored
        bottom-first (the *end* is the top of the deck, see `Player.library`),
        so "up" (toward the top of the deck) moves an object later in the
        list.
        """
        obj = self._object(action)
        direction = action.get("direction")
        if direction not in ("up", "down"):
            raise GameActionError("edit_reorder_object needs a direction: 'up' or 'down'")
        objs = self._zone_list_containing(obj)
        if objs is None:
            raise GameActionError("object is not in a reorderable (personal-zone) list")
        idx = objs.index(obj)
        new_idx = idx + (1 if direction == "up" else -1)
        if 0 <= new_idx < len(objs):
            objs[idx], objs[new_idx] = objs[new_idx], objs[idx]

    def _zone_list_containing(self, obj: GameObject) -> Optional[list[GameObject]]:
        """The actual (mutable) personal-zone list holding ``obj``, or None if
        it's on the battlefield or not found (battlefield order isn't
        meaningful — RULE 403 permanents have no inherent order)."""
        for player in self.engine.state.players:
            for objs in player.zones.values():
                if obj in objs:
                    return objs
        return None

    def _edit_set_flags(self, action: dict[str, Any]) -> None:
        obj = self._object(action)
        if "tapped" in action:
            obj.tapped = bool(action["tapped"])
        if "summoning_sick" in action:
            obj.summoning_sick = bool(action["summoning_sick"])
        if "attacking" in action:
            obj.attacking = bool(action["attacking"])
        if "damage_marked" in action:
            obj.damage_marked = max(0, int(action["damage_marked"]))

    def _edit_set_mana(self, action: dict[str, Any]) -> None:
        """Set one mana type in a player's pool to an absolute amount
        (RULE 106) — a puzzle setup convenience; normal play only ever
        adds/pays/empties mana, never sets it directly."""
        player = self._edit_player(action)
        mana_type = str(action.get("mana_type") or "")
        try:
            player.mana_pool.set_amount(mana_type, max(0, int(action.get("value", 0))))
        except ValueError as exc:
            raise GameActionError(str(exc)) from exc

    def _edit_commander_damage(self, action: dict[str, Any]) -> None:
        player = self._edit_player(action)
        cid = int(action["commander_id"])
        amount = max(0, int(action.get("value", 0)))
        if amount > 0:
            player.commander_damage[cid] = {
                "name": action.get("name", ""),
                "amount": amount,
            }
        else:
            player.commander_damage.pop(cid, None)

    def _edit_set_turn(self, action: dict[str, Any]) -> None:
        state = self.engine.state
        if "turn_number" in action:
            state.turn_number = max(1, int(action["turn_number"]))
        if action.get("active_player_id"):
            player = state.player_by_id(str(action["active_player_id"]))
            state.active_player_index = state.players.index(player)
        step = action.get("step")
        if step:
            state.current_step = str(step)
            state.current_phase = action.get("phase") or replay.phase_for_step(str(step))
            self.engine.resume_at(replay.cursor_after(str(step)))

    def _mulligan(self, player: Player) -> None:
        """London mulligan, part 1: shuffle the hand back and draw 7 (RULE 103.4-103.5)."""
        while player.hand:
            obj = player.hand.pop()
            obj.zone = Zone.LIBRARY
            player.library.append(obj)
        player.shuffle_library()
        player.draw(self._starting_hand)
        self._mulligan_count += 1

    def _keep_hand(
        self,
        player: Player,
        bottom_instance_ids: list[Any],
        draw_first: Optional[bool] = None,
    ) -> None:
        """London mulligan, part 2: keep, bottoming one card per mulligan taken.

        ``draw_first`` sets who draws on turn 1 (UC3 setup option): True →
        the human draws in their first turn (they're "on the draw"); False →
        they skip it (the standard "on the play" rule, RULE 103.7a). None
        keeps the session's current setting.
        """
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
        if draw_first is not None:
            self._draw_first = bool(draw_first)
        self.engine.state.skip_first_draw = not self._draw_first
        self._setup_complete = True

    def _apply_advance_to_decision(self) -> dict[str, Any]:
        """Fast-forward to the active player's next decision, one real step
        at a time (the "Nächste Entscheidung" button).

        Each iteration is a genuine `advance_step`, snapshotted and logged
        exactly like the single-step button, so every step's events fire and
        the move stays undoable step-by-step (Bug 1: deterministic, opponent
        or not). It always advances at least one step, then stops at the
        first step offering a real choice — the active player's main phases
        (always: that's where they develop their board), a castable/playable
        card, an eligible attacker, a pending choice, a non-empty stack, or
        game over. Setup/pending gates match `_dispatch`.
        """
        if not self._setup_complete:
            raise GameActionError("finish the mulligan phase before playing")
        if self.engine.state.pending_choice:
            raise GameActionError("a choice is pending — answer it first")
        for _ in range(_MAX_DECISION_ADVANCE_STEPS):
            self._snapshot("advance_step")
            self.engine.advance_step()
            self.move_log.append("advance_step")
            if self.engine.state.game_over or self._step_has_interaction():
                break
        return self.view()

    def _step_has_interaction(self) -> bool:
        """Whether the active player has a real decision at the current step.

        A pending choice, a non-empty stack or game-over always qualify. So do
        the active player's **main phases** — that's where they develop their
        board, so "Next decision" must never skip past them to combat (Bug 2)
        — as does any step where they can play a land, cast, or attack. A lone
        untapped mana source doesn't count (the pool empties each step's end).
        """
        state = self.engine.state
        if state.game_over or state.pending_choice or state.stack:
            return True
        if state.current_step in ("main1", "main2"):
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

    def _resolve_defender(self, defender: Any) -> Optional[dict[str, Any]]:
        """Validate a declared combat defender spec from the wire (RULE 508.1a).

        Accepts the ``{"kind": "player"|"planeswalker", ...}`` shape the UI
        sends (mirroring `GameEngine.legal_defenders_for`), or None for a
        bare swing. The engine re-validates it against the legal set; this
        only sanity-checks the payload shape and confirms the referenced
        object exists so a bad id fails as a clean action error.
        """
        if defender is None:
            return None
        if not isinstance(defender, dict):
            raise GameActionError("defender must be an object or null")
        kind = defender.get("kind")
        if kind == "player":
            player = self.engine.state.player_by_id(str(defender["id"]))
            return {"kind": "player", "id": player.id, "label": player.name}
        if kind == "planeswalker":
            obj = self._object_by_id(defender["instance_id"])
            return {"kind": "planeswalker", "instance_id": obj.instance_id, "label": obj.name}
        raise GameActionError(f"unknown defender kind: {kind!r}")

    @staticmethod
    def _resolve_tap_choices(tap_choices: Optional[list[Any]]) -> Optional[list[Any]]:
        """The player's pick of *which* permanents pay a "tap N untapped
        <type>s you control" cost (RULE 602.1, Birchlore Rangers/Heritage
        Druid) — just instance ids; `GameEngine` resolves and validates them
        against the eligible pool itself. ``None`` (not an empty list) when
        absent, so the engine falls back to its own auto-pick."""
        if tap_choices is None:
            return None
        return [int(i) for i in tap_choices]

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
            # A choice is pending: the only legal actions are answering it —
            # one per option (a decline option maps to the `decline` action).
            actions: list[dict[str, Any]] = []
            for opt in pending.get("options", []):
                if opt["id"] == "decline":
                    actions.append({"type": "decline"})
                else:
                    actions.append(
                        {
                            "type": "choose",
                            "option_id": opt["id"],
                            "name": opt.get("label"),
                            "instance_id": opt.get("instance_id"),
                        }
                    )
            return actions
        return self.engine.legal_actions(self.engine.state.active_player)

    def analysis(self) -> dict[str, Any]:
        """A per-player digest of the game so far for the end-of-game review.

        Derived from `GameState.stats`: totals (cards drawn/played, mana
        produced, damage), the mana-value curve of spells cast, and mana
        produced per turn. Cheap to recompute, so it's included in every
        view and the UI surfaces it when the game ends.
        """
        state = self.engine.state
        stats = state.stats
        players = {p.id: p for p in state.players}
        per_player: dict[str, Any] = {}
        for pid, bucket in stats["players"].items():
            cmcs = bucket["spell_cmcs"]
            curve: dict[int, int] = {}
            for value in cmcs:
                curve[value] = curve.get(value, 0) + 1
            mana_per_turn: dict[int, int] = {}
            for rec in stats["timeline"]:
                if rec["player_id"] == pid and rec["kind"] == "mana":
                    mana_per_turn[rec["turn"]] = mana_per_turn.get(rec["turn"], 0) + rec["amount"]
            player = players.get(pid)
            per_player[pid] = {
                "name": player.name if player else pid,
                "is_dummy": player.is_dummy if player else False,
                "life": player.life if player else None,
                "cards_drawn": bucket["cards_drawn"],
                "lands_played": bucket["lands_played"],
                "spells_cast": bucket["spells_cast"],
                "cards_played": bucket["lands_played"] + bucket["spells_cast"],
                "mana_produced": bucket["mana_produced"],
                "damage_dealt": bucket["damage_dealt"],
                "damage_taken": bucket["damage_taken"],
                "total_cmc_played": sum(cmcs),
                "avg_cmc": round(sum(cmcs) / len(cmcs), 2) if cmcs else 0,
                "cmc_curve": curve,
                "mana_per_turn": mana_per_turn,
            }
        return {"turns": state.turn_number, "players": per_player}

    def view(self) -> dict[str, Any]:
        """Everything the UI needs to render the session after a change."""
        # Refresh derived characteristics so the serialized board (P/T, types,
        # granted keywords, per-object trace) reflects the current layer stack
        # (RULE 613) even if nothing triggered an SBA since the last change.
        self.engine.recompute_continuous_effects()
        return {
            "session_id": self.id,
            "mode": self.mode,
            "state": self.engine.state.to_dict(),
            "legal_actions": self.legal_actions(),
            "pending_choice": self.engine.state.pending_choice,
            "can_rewind": self.can_rewind,
            "move_log": list(self.move_log),
            # Every static ability in play, for the UI's optional layer panel.
            "static_effects": continuous.active_static_abilities(self.engine.state),
            "setup": {
                "complete": self._setup_complete,
                "mulligan_count": self._mulligan_count,
                "draw_first": self._draw_first,
            },
            "analysis": self.analysis(),
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
            library, commanders, player_name, starting_life, starting_hand, with_dummy=True
        )
        session = GameSession(
            engine,
            mode=GOLDFISH,
            starting_hand=starting_hand,
            require_setup=True,
        )
        self._sessions[session.id] = session
        return session

    def create_replay(self, descriptor: dict[str, Any], loader: Any) -> GameSession:
        """Build a Replay/puzzle session from a descriptor (blank or loaded).

        Unlike goldfish there is no mulligan/setup gate and no auto-started
        turn — the board is given. ``loader`` is stashed on the session so
        `edit_add_object` can resolve card names on demand.
        """
        engine = replay.build_replay_engine(descriptor, loader)
        session = GameSession(engine, mode=REPLAY, require_setup=False)
        session._loader = loader
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

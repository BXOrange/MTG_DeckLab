"""Server-held game sessions: goldfish (with rewind/restart), replay, multiplayer.

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

Every action carries an **actor** (``apply_action(action, actor_id=...)``):
solo modes leave it implicit (the active player), multiplayer always names
it, and the engine itself does the rules validation either way — its
timing checks are already written against an explicit ``player`` argument
(`GameEngine.can_cast`'s RULE 601.3a active-player gate, `declare_blockers`'
"the attacking player does not declare blockers"), so a non-active player
naturally gets exactly the instant-speed/blocking subset and nothing more.

`view(perspective=...)` renders the session from one player's seat: hidden
zones belonging to *other* players are redacted server-side (RULE 400.2 —
a hand is a hidden zone; the client never receives what it may not see),
and `legal_actions` is computed for that seat rather than for whoever is
active.

`GameSessionManager` holds sessions in memory keyed by id (like
`game_ws.py`'s connection manager — single process, not persisted).
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
from mtg_analyzer.game.top_library import may_look_at_top_of_library
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

#: Mulligan rules a table can agree on before the game starts (RULE 103.4).
#: ``london`` is the current tournament rule — redraw a full hand, then put
#: one card per mulligan taken on the bottom when you keep. ``none`` skips
#: the whole procedure (the opening hand is the hand), which is what a quick
#: test game between two people usually wants. Vancouver's "scry 1 after
#: keeping" is deliberately absent: `RulesEngine.scry` is a non-interactive
#: stub that always keeps every card on top, so offering it would be a
#: choice with no effect (see backend/ToDo_Backend.md).
MULLIGAN_STYLES = ("london", "none")


class GameActionError(Exception):
    """An action was illegal or malformed for the current game state."""


class MultiplayerNotImplementedError(Exception):
    """Retained for the legacy ``POST /api/game/multiplayer`` stub route.

    Multiplayer itself is implemented now (`GameSessionManager.
    create_multiplayer`, driven by `services/lobby.py` and
    `api/multiplayer.py`); the old bare "start a multiplayer game with no
    lobby behind it" entry point stays a 501 because a session needs seats
    — decks, names, an agreed mulligan style — that only the lobby has.
    """


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


def build_multiplayer_engine(
    seats: list[dict[str, Any]],
    starting_life: int = 40,
    starting_hand: int = 7,
) -> GameEngine:
    """Build an N-real-player `GameEngine` and deal every opening hand (UC4).

    Each seat is ``{"player_id", "name", "library": [Card], "commanders":
    [Card]}`` — the same per-player material `build_goldfish_engine` builds
    for its single human, once per seat and with no passive dummy: every
    player here takes real turns (`GameState.next_active_index` rotates
    through them) and every one of them gets an opening hand.

    Seat order is turn order; the first seat is the starting player (RULE
    103.2 — who goes first is decided in the lobby, by seat order, rather
    than by a die roll the server would have to arbitrate).
    """
    players: list[Player] = []
    for seat in seats:
        player = Player(id=str(seat["player_id"]), name=str(seat.get("name") or seat["player_id"]),
                        life=starting_life)
        for card in seat.get("library") or []:
            obj = GameObject(card, owner_id=player.id, zone=Zone.LIBRARY)
            bind_from_catalogue(obj)  # bind-on-load: card text → live abilities
            player.library.append(obj)
        for card in seat.get("commanders") or []:
            obj = GameObject(card, owner_id=player.id, zone=Zone.COMMAND, is_commander=True)
            bind_from_catalogue(obj)
            player.add_to_zone(obj, Zone.COMMAND)
        players.append(player)

    state = GameState(players=players)
    engine = GameEngine(state)
    for player in players:
        player.draw(starting_hand)
    engine.start()
    return engine


def _redact_hidden_zones(
    state_dict: dict[str, Any],
    perspective: Optional[str],
    top_library_visible: Optional[dict[str, bool]] = None,
) -> None:
    """Strip every player's hidden zones from a serialized state, in place.

    RULE 400.2: the library and the hand are hidden zones. ``perspective``
    is the one seat exempted — its own hand stays, and so does its own
    top-of-library card when something lets it look (RULE 601.3b-adjacent,
    `game/top_library.py`). ``None`` exempts nobody, which is what a
    spectator gets.

    Redaction happens here rather than in the client because the client is
    not trustworthy: an opponent's hand must never be *sent*, not merely
    left unrendered. ``library_count``/``hand_count`` are untouched, so the
    board can still draw the right number of face-down cards.

    Not yet redacted: a face-down card in exile (RULE 701.20a,
    `GameObject.face_down_in_exile`) still ships its identity — no card in
    the multiplayer path produces one today, and doing it properly means
    redacting a *card's* characteristics rather than a whole zone (see
    backend/ToDo_Backend.md).
    """
    for player in state_dict.get("players", []):
        own = perspective is not None and player.get("id") == perspective
        if not own:
            player["hand"] = []
        # A library is hidden even from its owner (they don't know their own
        # draw order); only a card an effect actually reveals is kept.
        top_visible = own and (top_library_visible or {}).get(player.get("id"))
        player["library"] = player["library"][-1:] if top_visible and player["library"] else []

    # A pending choice is answered by exactly one player; nobody else may
    # see its options (they can name cards in a hidden zone). Everyone else
    # gets a passive "waiting on X" marker instead — see `view`.
    pending = state_dict.get("pending_choice")
    if pending and pending.get("player_id") != perspective:
        state_dict["pending_choice"] = None
        state_dict["waiting_on_choice"] = {
            "player_id": pending.get("player_id"),
            "kind": pending.get("kind"),
            "prompt": pending.get("prompt") or pending.get("description") or "",
        }


class GameSession:
    """A running game with undo history and restart."""

    def __init__(
        self,
        engine: GameEngine,
        mode: str = GOLDFISH,
        session_id: Optional[str] = None,
        starting_hand: int = 7,
        require_setup: bool = False,
        mulligan_style: str = "london",
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
        #: Which mulligan procedure the table agreed on (`MULLIGAN_STYLES`).
        self.mulligan_style = mulligan_style if mulligan_style in MULLIGAN_STYLES else "london"
        #: How many mulligans each player has taken (London mulligan: each
        #: one redraws 7, then keeping puts that many cards on the bottom).
        #: Per-player because in multiplayer every seat mulligans for itself,
        #: independently and in parallel (RULE 103.4 resolves them in turn
        #: order, but nothing about one player's decision depends on
        #: another's, so there is no reason to serialize them).
        self._mulligan_counts: dict[str, int] = {}
        #: Seats that still have to keep a hand before play starts. Empty
        #: means setup is done; goldfish/replay start it empty or with the
        #: single human in it.
        self._setup_pending: set[str] = (
            {p.id for p in engine.state.players if not p.is_dummy} if require_setup else set()
        )
        #: RULE 117: whether priority is genuinely passed around the table
        #: rather than auto-drained. Only a shared game needs it — there is
        #: nobody to pass to in a solo one. Kept on the session as well as
        #: the engine because `_restore` (rewind/restart) builds a *fresh*
        #: engine and has to re-arm it.
        self.interactive_priority = mode == MULTIPLAYER
        engine.interactive_priority = self.interactive_priority
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
        self.engine.interactive_priority = self.interactive_priority
        self.engine.resume_at(cursor)

    @property
    def can_rewind(self) -> bool:
        return bool(self._history)

    @property
    def _setup_complete(self) -> bool:
        """Whether every seat has kept a hand and play can begin."""
        return not self._setup_pending

    def restart(self) -> dict[str, Any]:
        """Reset to the opening state (UC3: 'jederzeit neu starten')."""
        state, cursor = self._initial
        self._restore(state, cursor)
        self._history.clear()
        self.move_log.clear()
        self._mulligan_counts.clear()
        self._setup_pending = (
            {p.id for p in self.engine.state.players if not p.is_dummy}
            if self._require_setup
            else set()
        )
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

    def apply_action(
        self, action: dict[str, Any], actor_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Validate + apply one action, snapshotting first so it can be undone.

        ``actor_id`` names the player taking it; ``None`` (every solo mode)
        means the active player. The engine does the actual rules validation
        against that player — a non-active actor therefore gets exactly the
        instant-speed subset RULE 601.3a allows, plus blocking, and nothing
        else, without this layer having to enumerate what those are.

        Raises `GameActionError` for anything illegal, leaving the game
        untouched (the pre-action snapshot is restored on failure).
        """
        if not isinstance(action, dict) or "type" not in action:
            raise GameActionError("action must be a dict with a 'type'")
        actor = self._actor(actor_id)
        # "Next decision" is a fast-forward, but it must remain a sequence of
        # ordinary steps — each a real, separately snapshotted/logged
        # `advance_step` firing its own events — so the game evolves exactly
        # as clicking "Next step" would, and undo/replay stay deterministic
        # even with the opponent present. It manages its own history entries.
        if action["type"] in ("advance_to_decision", "next_decision"):
            if actor is not self.engine.state.active_player:
                raise GameActionError("only the active player can advance the turn")
            return self._apply_advance_to_decision()
        label = self._describe(action)
        self._snapshot(label)
        try:
            self._dispatch(action, actor)
        except (ValueError, KeyError) as exc:
            # Roll back the failed attempt so state stays clean.
            _, snapshot, cursor = self._history.pop()
            self._restore(snapshot, cursor)
            raise GameActionError(str(exc)) from exc
        self.move_log.append(label)
        return self.view()

    def _actor(self, actor_id: Optional[str]) -> Player:
        """The player an action is taken by — named, or the active player."""
        if actor_id is None:
            return self.engine.state.active_player
        try:
            return self.engine.state.player_by_id(str(actor_id))
        except KeyError as exc:
            raise GameActionError(f"no player with id {actor_id!r}") from exc

    def concede(self, player_id: str) -> dict[str, Any]:
        """RULE 104.3a: ``player_id`` leaves the game (the "Aufgeben" button).

        Legal at any time and from any seat — conceding doesn't use the
        stack and doesn't need priority — so unlike `apply_action` it is not
        routed through `_dispatch`'s timing gates. Snapshotted like any
        other move so a misclick is still rewindable in a friendly game.
        """
        player = self._actor(player_id)
        self._snapshot(f"concede: {player.name}")
        self.engine.rules.concede(player)
        # RULE 104.3a leaves the game *now*, so a seat that hadn't kept its
        # opening hand yet must stop blocking the rest of the table.
        self._setup_pending.discard(player.id)
        self.move_log.append(f"concede: {player.name}")
        return self.view()

    def _dispatch(self, action: dict[str, Any], actor: Optional[Player] = None) -> None:
        state = self.engine.state
        active = actor if actor is not None else state.active_player
        kind = action["type"]

        # Replay/puzzle board editing (mode == REPLAY): direct state
        # mutations that bypass rules validation, so an arbitrary — even
        # rules-illegal — position can be constructed. Allowed at any time.
        if kind.startswith("edit_"):
            self._edit_dispatch(action)
            return

        # Setup phase (UC3: mulligan before the game proper starts): only
        # `mulligan`/`keep_hand` are legal until every seat's opening hand is
        # kept. In multiplayer each seat runs its own copy of this in
        # parallel, so the gate is per-actor (`_setup_pending`) rather than
        # global — a player who has already kept can't mulligan again while
        # waiting for the others.
        if not self._setup_complete:
            if active.id not in self._setup_pending:
                raise ValueError("you have already kept your opening hand")
            if kind == "mulligan":
                if self.mulligan_style == "none":
                    raise ValueError("this game is being played without mulligans")
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

        # RULE 117.1: with priority genuinely being passed around, only the
        # player holding it may take an action. `legal_actions` already
        # filters on this, but that's a *hint* to the UI — the rule has to
        # be enforced where actions actually arrive, or a client could
        # simply post one it was never offered. Exempt: RULE 509.1a's
        # declare-blockers (a turn-based action, taken by the defending
        # player while the attacker holds priority) and answering a pending
        # choice (nobody holds priority while the game is blocked on one).
        if (
            self.interactive_priority
            and kind not in ("declare_blockers", "choose", "decline")
            and state.priority_player is not None
            and active is not state.priority_player
        ):
            raise ValueError(f"{active.name} does not have priority")

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

        if kind in ("advance_step", "advance", "next_step", "auto_turn"):
            # Moving the turn on belongs to whoever's turn it is (RULE 500.1
            # — the active player is the one who runs out of things to do
            # first). Solo modes pass no actor and are unaffected.
            if active is not state.active_player:
                raise ValueError("only the active player can advance the turn")
            if self.interactive_priority:
                # RULE 117.4: a step doesn't end because someone decided it
                # should — it ends when *all* players pass in succession on
                # an empty stack. Passing is the only way forward here, and
                # `_pass_priority` ends the step itself once that happens.
                raise ValueError("pass priority instead — the step ends when everyone passes")

        if kind in ("advance_step", "advance", "next_step"):
            # Advance exactly one step — no auto-skip, no auto-wait. The
            # player visits every step (untap, upkeep, draw, both mains, each
            # combat step, …) one click at a time.
            self.engine.advance_step()
            return


        if kind == "pass_priority":
            # Pass priority once: resolve the top of the stack (RULE 117),
            # one object at a time so instants can be cast in response.
            if self.interactive_priority:
                self._pass_priority(active)
            else:
                self.engine.pass_priority()
            return

        if kind == "auto_turn":
            self._auto_turn()
            return

        if kind == "play_land":
            face = action.get("face", "front")
            self.engine.play_land(active, self._object(action), face=face)
            return

        if kind == "set_skip_untap":
            # RULE 502.1 "you may choose not to untap ~ during your untap
            # step" — a standing toggle (`GameEngine.set_skip_untap`), not a
            # per-turn prompt; see its docstring for why.
            self.engine.set_skip_untap(active, self._object(action), bool(action.get("value", True)))
            return

        if kind == "tap_for_mana":
            option_index = int(action.get("option_index", 0))
            ability_index = int(action.get("ability_index", 0))
            tap_choices = self._resolve_tap_choices(action.get("tap_choices"))
            color_split = self._resolve_color_split(action.get("color_split"))
            self.engine.tap_for_mana(
                active, self._object(action), option_index, ability_index, tap_choices,
                color_split=color_split,
            )
            return

        if kind == "activate_hand_mana":
            # RULE 605.1a "Exile this card from your hand: Add …" (Elvish/
            # Simian Spirit Guide) — `tap_for_mana`'s hand-zone counterpart.
            option_index = int(action.get("option_index", 0))
            ability_index = int(action.get("ability_index", 0))
            color_split = self._resolve_color_split(action.get("color_split"))
            self.engine.activate_hand_mana_ability(
                active, self._object(action), option_index, ability_index,
                color_split=color_split,
            )
            return

        if kind == "cast_spell":
            # The spell goes on the stack; it does NOT auto-resolve, so the
            # player can respond (cast an instant) or pass priority to let
            # it resolve — real stack interaction (RULE 608).
            targets = self._resolve_targets(action.get("targets"))
            target_groups = self._resolve_target_groups(action.get("target_groups"))
            x = int(action.get("x", 0))
            face = action.get("face", "front")
            # RULE 700.2: a modal spell's chosen mode — an index into
            # `obj.spell_modes`, or "both" (RULE 700.2e) — round-trips from
            # the `mode` field `GameEngine._cast_action` stamped on the
            # offered action; absent for a non-modal spell.
            mode = action.get("mode")
            # RULE 702.33: how many times Kicker was paid — round-trips from
            # `legal_actions`' `has_kicker`/`kicker_multi`/`max_kicker` the
            # same way `x` round-trips from `has_x`/`max_x`.
            kicked = int(action.get("kicked", 0))
            # The remaining optional cost toggles round-trip the same way,
            # each off the flag `GameEngine._cast_action` stamps when the
            # spell offers it: RULE 702.27 Buyback (``has_buyback``), RULE
            # 702.140b Mutate, RULE 701.x Bargain, and RULE 702.42a Entwine
            # (``entwine``, which is what makes ``mode="both"`` legal on an
            # otherwise "choose one" block).
            self.engine.cast_spell(
                active, self._object(action), targets, x, face=face, mode=mode,
                kicked=kicked, target_groups=target_groups,
                buyback=bool(action.get("buyback", False)),
                mutate=bool(action.get("mutate", False)),
                mutate_under=bool(action.get("mutate_under", False)),
                bargained=bool(action.get("bargained", False)),
                entwine=bool(action.get("entwine", False)),
            )
            return

        if kind == "activate_ability":
            # Pay the ability's cost and put it on the stack (RULE 602); like a
            # spell it then waits for priority to resolve.
            targets = self._resolve_targets(action.get("targets"))
            target_groups = self._resolve_target_groups(action.get("target_groups"))
            x = int(action.get("x", 0))
            index = int(action.get("ability_index", 0))
            tap_choices = self._resolve_tap_choices(action.get("tap_choices"))
            self.engine.activate_ability(
                active, self._object(action), index, targets, x, tap_choices,
                target_groups=target_groups,
            )
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
            # blocks). The actor *is* the defender in multiplayer; an
            # explicit ``player_id`` is honoured only for the solo/replay
            # case where no actor is threaded through, and it otherwise
            # falls back to the first non-active player.
            defender_id = action.get("player_id")
            blocker_player = (
                active
                if active is not state.active_player
                else state.player_by_id(defender_id)
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

    def mulligan_count_for(self, player_id: str) -> int:
        """How many mulligans ``player_id`` has taken (0 if none)."""
        return self._mulligan_counts.get(str(player_id), 0)

    def _mulligan(self, player: Player) -> None:
        """London mulligan, part 1: shuffle the hand back and draw 7 (RULE 103.4-103.5)."""
        while player.hand:
            obj = player.hand.pop()
            obj.zone = Zone.LIBRARY
            player.library.append(obj)
        player.shuffle_library()
        player.draw(self._starting_hand)
        self._mulligan_counts[player.id] = self.mulligan_count_for(player.id) + 1

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
        keeps the session's current setting. Multiplayer never sends it —
        there the starting player is simply the first seat and skips the
        draw, so the flag stays at its RULE 103.7a default.
        """
        bottom_count = self.mulligan_count_for(player.id)
        if len(bottom_instance_ids) != bottom_count:
            raise ValueError(
                f"must put exactly {bottom_count} card(s) on the bottom of the library"
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
        self._setup_pending.discard(player.id)
        if self.interactive_priority and not self._setup_pending:
            # Everyone has kept: run the game into its first real priority
            # window. Nothing else can do this — with RULE 117.4 driving the
            # turn, a step only ends when players pass, and nobody can pass
            # before somebody holds priority in the first place.
            self._advance_to_priority_window()

    # -- Interactive priority (RULE 117, multiplayer only) --------------

    def _pass_priority(self, player: Player) -> None:
        """``player`` passes; the table moves on (RULE 117.3-4).

        `GameEngine.pass_priority(player)` already owns the round itself:
        it records the pass, hands priority to the next living player in
        APNAP order, and — once everyone has passed in succession —
        resolves the top of the stack and gives priority back to the
        active player (RULE 117.3b).

        The one thing it can't do is end the *step*, because it doesn't
        drive the turn: RULE 117.4's other half says that when all players
        pass with an **empty** stack, the phase or step ends instead. That
        is this method's job, and it's why "Nächster Schritt" isn't an
        action in a shared game — nobody decides a step is over, it simply
        runs out of players who want to do something.
        """
        state = self.engine.state
        holder = state.priority_player
        if holder is not None and player is not holder:
            raise ValueError(f"{player.name} does not have priority")
        # Whether this pass completes the round has to be read *before* the
        # engine clears `priority_passed` as part of handling it.
        living = {p.id for p in state.living_players()}
        completes_round = living <= (state.priority_passed | {player.id})
        stack_was_empty = not state.stack

        resolved = self.engine.pass_priority(player)
        if resolved or not completes_round or not stack_was_empty:
            return
        # Everyone passed on an empty stack → the step ends.
        self._advance_to_priority_window()

    def _advance_to_priority_window(self) -> None:
        """Run steps until one opens a priority window (or the game ends).

        Untap and cleanup (RULE 502/514) give nobody priority, so stopping
        in them would leave the table with no legal action at all and no
        way out. Advancing straight through them lands on the next step
        where somebody actually gets to act.
        """
        for _ in range(_MAX_DECISION_ADVANCE_STEPS):
            if self.engine.advance_step() is None:
                return  # game over
            if self.engine.state.game_over or self.engine.state.priority_player is not None:
                return

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

    @staticmethod
    def _resolve_color_split(color_split: Optional[dict[str, Any]]) -> Optional[dict[str, int]]:
        """The player's chosen colour distribution for an "any combination
        of colours" mana ability (`ManaAbility.any_combination`); ``None``
        when absent, so `GameEngine.tap_for_mana` falls back to
        ``option_index``'s single-colour choice."""
        if color_split is None:
            return None
        return {str(color): int(count) for color, count in color_split.items()}

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

    def _resolve_target_groups(
        self, target_groups: Optional[list[list[Any]]]
    ) -> Optional[list[list[Any]]]:
        """`_resolve_targets`, per group — RULE 115.1/601.2c's per-effect
        target partitioning (`StackItem.target_groups`) for a spell/ability
        with 2+ *different* targeting effects. Only meaningful when the
        action payload explicitly groups its target picks by requirement
        (``requirements_with_targets``' order); an ordinary single-
        targeting-effect action never needs this (``target_groups`` absent,
        the plain flat ``targets`` list is all that's ever used)."""
        if not target_groups:
            return None
        return [self._resolve_targets(group) or [] for group in target_groups]

    @staticmethod
    def _describe(action: dict[str, Any]) -> str:
        name = action.get("name")
        kind = action["type"]
        return f"{kind}: {name}" if name else kind

    # -- Views ---------------------------------------------------------

    def legal_actions(self, perspective: Optional[str] = None) -> list[dict[str, Any]]:
        """What ``perspective`` may do right now (default: the active player).

        In a multiplayer session every client asks for its own seat, so a
        non-active player is offered exactly what the engine says they may
        legally do — respond at instant speed, declare blockers — instead of
        being shown the active player's options.
        """
        state = self.engine.state
        seat = self._actor(perspective) if perspective is not None else state.active_player
        if not self._setup_complete:
            if seat.id not in self._setup_pending:
                return []  # already kept; waiting on the rest of the table
            # `bottom_count` tells the UI how many cards `keep_hand` must
            # bottom this time (0 on the very first hand, before any
            # mulligan has been taken).
            actions: list[dict[str, Any]] = []
            if self.mulligan_style != "none":
                actions.append({"type": "mulligan"})
            actions.append({"type": "keep_hand", "bottom_count": self.mulligan_count_for(seat.id)})
            return actions
        pending = state.pending_choice
        if pending:
            # A choice is pending: the only legal actions are answering it —
            # one per option (a decline option maps to the `decline` action) —
            # and only for the player it's addressed to (`pending["player_id"]`).
            if perspective is not None and pending.get("player_id") not in (None, seat.id):
                return []
            actions = []
            # (falls through to the option list below)
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
        if self.interactive_priority and state.priority_player is not None:
            # RULE 117.1: only the player who *has* priority may act. A
            # non-holder is offered nothing at all — with one exception,
            # RULE 509.1a's declare-blockers turn-based action, which isn't
            # taken with priority (the defending player declares blocks
            # while the active player still holds it).
            if seat is not state.priority_player:
                return [
                    action
                    for action in self.engine.legal_actions(seat)
                    if action["type"] == "declare_blockers"
                ]
        return self.engine.legal_actions(seat)

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

    def view(self, perspective: Optional[str] = None) -> dict[str, Any]:
        """Everything the UI needs to render the session after a change.

        ``perspective`` is the seat the view is *for*: its `legal_actions`
        are that player's, and every other player's hidden zones (RULE
        400.2) are redacted out of the payload rather than merely hidden by
        the client — the opponent's hand never leaves the server. ``None``
        (solo modes, and the observer view via `observer_view`) keeps the
        full, unredacted state.
        """
        # Refresh derived characteristics so the serialized board (P/T, types,
        # granted keywords, per-object trace) reflects the current layer stack
        # (RULE 613) even if nothing triggered an SBA since the last change.
        self.engine.recompute_continuous_effects()
        state_dict = self.engine.state.to_dict()
        top_visible = {
            p.id: may_look_at_top_of_library(p, self.engine.state)
            for p in self.engine.state.players
        }
        if perspective is not None:
            _redact_hidden_zones(state_dict, perspective, top_visible)
        return {
            "session_id": self.id,
            "mode": self.mode,
            "perspective": perspective,
            "state": state_dict,
            "legal_actions": self.legal_actions(perspective),
            "pending_choice": state_dict.get("pending_choice"),
            "can_rewind": self.can_rewind,
            "move_log": list(self.move_log),
            # Every static ability in play, for the UI's optional layer panel.
            "static_effects": continuous.active_static_abilities(self.engine.state),
            # RULE 603.7 delayed triggered abilities armed but not yet fired
            # ("at the beginning of your next upkeep/the next end step, …"),
            # for the UI's "planned" panel (Ephemerate's Rebound/Marchesa's
            # counter-death return/Sneak Attack's delayed sacrifice-shaped).
            "delayed_triggers": [dt.to_dict() for dt in self.engine.state.delayed_triggers],
            # Recurring player-scoped triggers armed for a bounded duration
            # (Nuka-Nuke Launcher's "until the end of defending player's
            # next turn, ..."), same "planned" panel as delayed_triggers.
            "temporary_player_triggers": [
                t.to_dict() for t in self.engine.state.temporary_player_triggers
            ],
            # Which players currently have a "play with the top card of your
            # library revealed"-shaped permission active (Oracle of Mul
            # Daya/Glarb, Calamity's Augur-shaped, `game/top_library.py`) —
            # the board only renders a player's own top-of-library card when
            # this is true for them; whether it's actually playable/castable
            # from there is conveyed the ordinary way, through
            # ``legal_actions``' per-instance offers.
            "top_library_visible": top_visible,
            # RULE 117, shared games only: who holds priority right now, who
            # has already passed in this round, and whether priority is
            # played out at all (a solo session auto-drains and never has a
            # holder to show). The board reads this to say "du bist dran" /
            # "warte auf X" and to drive the auto-pass countdown.
            "priority": {
                "interactive": self.interactive_priority,
                "player_id": (
                    self.engine.state.priority_player.id
                    if self.engine.state.priority_player
                    else None
                ),
                "passed": sorted(self.engine.state.priority_passed),
            },
            "setup": {
                "complete": self._setup_complete,
                "mulligan_style": self.mulligan_style,
                # This seat's own mulligan count (the number of cards its
                # `keep_hand` must bottom); solo modes have only one seat.
                "mulligan_count": self.mulligan_count_for(
                    perspective if perspective is not None else self.engine.state.active_player.id
                ),
                "draw_first": self._draw_first,
                # Who the table is still waiting on, so a player who has
                # already kept sees "waiting for X" instead of a dead screen.
                "waiting_for": sorted(self._setup_pending),
            },
            "analysis": self.analysis(),
        }

    def observer_view(self) -> dict[str, Any]:
        """A spectator's view: the public board, nobody's hand (RULE 400.2).

        Built by redacting against a seat that doesn't exist, so *every*
        player's hidden zones are stripped — an observer is not a player and
        has no hand of their own to be shown. `legal_actions` is empty for
        the same reason: watching is not playing.
        """
        view = self.view()
        _redact_hidden_zones(view["state"], perspective=None)
        view["perspective"] = None
        view["observer"] = True
        view["legal_actions"] = []
        view["pending_choice"] = view["state"].get("pending_choice")
        return view


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

    def create_multiplayer(
        self,
        seats: list[dict[str, Any]],
        starting_life: int = 40,
        starting_hand: int = 7,
        mulligan_style: str = "london",
    ) -> GameSession:
        """Start an N-real-player game (UC4), one seat per human.

        ``seats`` is `build_multiplayer_engine`'s shape; seat order is turn
        order. Every seat mulligans for itself before play begins, so the
        session starts in the setup phase with all of them pending.
        """
        if len(seats) < 2:
            raise MultiplayerNotImplementedError("a multiplayer game needs at least two seats")
        engine = build_multiplayer_engine(seats, starting_life, starting_hand)
        session = GameSession(
            engine,
            mode=MULTIPLAYER,
            starting_hand=starting_hand,
            require_setup=True,
            mulligan_style=mulligan_style,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> GameSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def remove(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

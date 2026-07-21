"""GameState: the whole shared game (RULE 100, RULE 400 shared zones).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R1.3 (Game State), R4.1 (Game
Loop), docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md.

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

from .events import EventType, GameEvent
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

    ``source`` is the permanent an *ability* item's stack image/overlay is
    shown for — a triggered ability's `TriggeredAbility.source` or an
    activated ability's own permanent (RULE 113.7a: the source of a
    granted ability is the object that has it, not whatever granted it).
    ``None`` for a spell (``obj`` already *is* the thing on the stack) or
    for the rare hand-built ability with no bound source.

    ``target_groups``, when given, partitions ``targets`` by *which*
    targeting effect in ``effects`` it belongs to (index-aligned: group 0
    is the first effect with a ``target_spec``, group 1 the second, …;
    an effect with no ``target_spec`` consumes no group). This is what lets
    2+ *different* targeting effects on one spell/ability each resolve
    against their own targets instead of all reading off the front of one
    shared ``targets`` list (RULE 115.1/601.2c — see
    `docs/implementation-state/ToDo_Backend.md`). ``None`` (the common
    case: at most one targeting effect) keeps the legacy behaviour of every
    effect reading ``targets`` directly.
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
        source: Optional[GameObject] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        self.kind = kind
        self.controller_id = controller_id
        self.effects = effects or []
        self.obj = obj
        self.description = description
        self.targets = targets or []
        self.target_groups = target_groups
        self.x = x
        self.category = category or self._derive_category()
        self.source = source

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
            # An ability item's source permanent (None for a spell — `object`
            # above already covers it) — the UI shows this card's image with
            # the ability text overlaid, and a link back to it.
            "source": self.source.to_dict() if self.source else None,
        }

    def __repr__(self) -> str:
        label = self.description or (self.obj.name if self.obj else self.kind)
        return f"StackItem({self.kind} {label!r})"


class DelayedTrigger:
    """A delayed triggered ability (RULE 603.7) waiting for a future step.

    Created by a resolving spell/ability ("at the beginning of your next
    upkeep, …"). ``controller_id`` is who set it up (and, for ``scope ==
    "controller"``, whose step it waits for); ``step`` is the step-name it
    fires at (``"upkeep"``/``"main1"``/``"end"``/…); ``scope`` is
    ``"controller"`` (the controller's next such step) or ``"any"`` (the very
    next such step, regardless of whose turn — Corpse Dance's "the next end
    step"). ``effects`` are the already-built one-shot `GameEffect`s to place
    on the stack when it fires, ``targets`` any baked-in objects they act on.
    It fires exactly once — `GameEngine._fire_delayed_triggers` removes it
    after placing it. Plain data (built effects hold no engine reference), so
    it deep-copies with `GameState.clone`.
    """

    def __init__(
        self,
        controller_id: str,
        step: str,
        effects: list[Any],
        scope: str = "controller",
        targets: Optional[list[Any]] = None,
        description: str = "",
        min_turn: int = 0,
    ) -> None:
        self.controller_id = controller_id
        self.step = step
        self.effects = effects
        self.scope = scope
        self.targets = targets or []
        self.description = description
        #: The earliest ``turn_number`` this may fire at — 0 means "the very
        #: next matching step". Lets "at the beginning of *that* (extra) turn's
        #: end step" (Final Fortune) skip the *current* turn's end step by
        #: arming with ``min_turn = turn_number + 1``.
        self.min_turn = min_turn

    def __repr__(self) -> str:
        return f"DelayedTrigger({self.controller_id} @ {self.scope} {self.step!r})"

    def to_dict(self) -> dict[str, Any]:
        """For the UI's "planned" delayed-trigger panel — plain descriptive
        fields only (``effects`` are live `GameEffect` objects, not
        serializable, and not needed to just *announce* what's armed).
        ``source`` mirrors `StackItem.to_dict()`'s own field: the first
        baked effect's ``source`` (every effect a `DelayedTrigger` carries
        shares one, since one card/ability sets the whole thing up), so the
        board can show that permanent's art the same way a stack item does.
        """
        source = getattr(self.effects[0], "source", None) if self.effects else None
        return {
            "controller_id": self.controller_id,
            "step": self.step,
            "scope": self.scope,
            "description": self.description,
            "min_turn": self.min_turn,
            "source": source.to_dict() if source is not None else None,
        }


class TemporaryPlayerTrigger:
    """A *recurring*, bounded-duration ability installed on a **player**
    rather than a permanent (RULE 603.7-adjacent) — "until the end of
    defending player's next turn, that player gets two rad counters
    whenever they cast a spell" (Nuka-Nuke Launcher). Unlike
    `DelayedTrigger` (a one-shot future firing this fires *every* time its
    own ``event_type`` occurs while active, tracked by a small phase state
    machine `RulesEngine._collect_temporary_player_triggers` drives off
    `EventType.TURN_BEGIN`:

    * ``"waiting"`` — ``player_id``'s own next turn hasn't started yet
      (armed mid-turn, so their *current* turn — if any is in progress —
      doesn't count).
    * ``"active"`` — currently within that turn; re-fires on every
      matching ``event_type``.
    * Removed the moment the *next* `TURN_BEGIN` (anyone's) arrives after
      ``active_since_turn`` — that next turn beginning is what "the end of
      [their] turn" means operationally, since this engine has no separate
      "turn actually ended" event of its own to key off instead.

    Plain data (built effects hold no engine reference), so it deep-copies
    with `GameState.clone`.
    """

    def __init__(
        self,
        player_id: str,
        event_type: str,
        effects: list[Any],
        install_turn: int,
        description: str = "",
    ) -> None:
        self.player_id = player_id
        self.event_type = event_type
        self.effects = effects
        self.install_turn = install_turn
        self.phase = "waiting"
        self.active_since_turn: Optional[int] = None
        self.description = description

    def __repr__(self) -> str:
        return f"TemporaryPlayerTrigger({self.player_id} @ {self.event_type!r}, phase={self.phase!r})"

    def to_dict(self) -> dict[str, Any]:
        """For the UI's "planned" panel — mirrors `DelayedTrigger.to_dict()`."""
        source = getattr(self.effects[0], "source", None) if self.effects else None
        return {
            "player_id": self.player_id,
            "event_type": self.event_type,
            "phase": self.phase,
            "description": self.description,
            "source": source.to_dict() if source is not None else None,
        }


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
        #: Ids of living players who have passed priority in succession since
        #: the last state change (a spell/ability resolved, a new step began).
        #: When this covers every living player, the top of the stack
        #: resolves (or the step ends) — RULE 117.4. Only meaningful once an
        #: interactive multiplayer priority loop is driving `pass_priority`
        #: with an explicit player; solo goldfishing never populates it.
        self.priority_passed: set[str] = set()
        self.current_phase: str = ""
        self.current_step: str = ""

        #: The shared battlefield (RULE 403) and the stack (RULE 405).
        self.battlefield: list[GameObject] = []
        self.stack: list[StackItem] = []

        self.game_over = False
        self.winner_id: Optional[str] = None

        #: RULE 725/726: the monarch/initiative are designations, not
        #: objects — at most one player id each, ``None`` until an effect
        #: first grants one. `RulesEngine.become_monarch`/`take_initiative`
        #: set these; `RulesEngine._collect_inherent_triggers` reads them to
        #: fire the (source-less) triggered abilities RULE 725.2/726.2
        #: attach to holding either designation.
        self.monarch_id: Optional[str] = None
        self.initiative_id: Optional[str] = None

        #: Reproducible-randomness state (RULE 706 — "choose … at random", coin
        #: flips): a seed plus a monotonically-advancing counter. `RulesEngine.
        #: random_int` derives each draw from ``(rng_seed, rng_counter)`` and
        #: bumps the counter, so results are deterministic given the seed and
        #: survive `clone()`/undo exactly (a live `random.Random` instance
        #: wouldn't travel with the state). Plain ints — deep-copy with the
        #: state. A test can pin ``rng_seed`` for a fixed sequence.
        self.rng_seed: int = uuid.uuid4().int & 0xFFFFFFFF
        self.rng_counter: int = 0

        #: Whether the starting player skips their turn-1 draw (RULE 103.7a).
        #: True by default ("on the play"); the goldfish setup screen can turn
        #: it off so the human draws on turn 1 instead ("on the draw").
        self.skip_first_draw: bool = True

        #: A player decision the engine is waiting on (e.g. a library
        #: search) before it can keep resolving — plain JSON-able data
        #: (kind, player_id, eligible instance ids, …) so it survives a
        #: `clone()` for rewind and serializes to the UI. None when the
        #: engine isn't blocked on a choice. Set/consumed by the rules
        #: engine (mtg_analyzer/game/rules_engine.py).
        self.pending_choice: Optional[dict[str, Any]] = None

        #: A temporary "you may play this card" permission granted to a
        #: card sitting outside hand/command/graveyard/library-top (Light
        #: Up the Stage-shaped "exile, play until the end of your next
        #: turn" impulsive draw — RULE 601.3b analogue) — ``instance_id ->
        #: turn granted``. Distinct from the standing, battlefield-sourced
        #: permission `game/top_library.py` tracks: this one is turn-scoped
        #: and survives independently of any permanent, so it can't be
        #: continuously re-derived the way that one is. Set by
        #: `RulesEngine.exile_with_play_permission`, checked by
        #: `GameEngine.can_cast`/`can_play_land`, swept at cleanup
        #: (`GameEngine._step_cleanup`).
        self.temp_play_permissions: dict[int, int] = {}

        #: The name of whatever granted each `temp_play_permissions` entry
        #: (e.g. "Light Up the Stage"), so the board can explain *why* an
        #: exiled card is castable — a sibling dict rather than widening
        #: `temp_play_permissions`' own `int` values, to leave every existing
        #: turn-keyed reader of that dict alone. Set by `RulesEngine.
        #: exile_with_play_permission`; pruned in lockstep with
        #: `temp_play_permissions` at cleanup (`GameEngine._step_cleanup`).
        #: Absent key (not just falsy) means "unknown source" — an older
        #: save/replay snapshot predating this field, or a caller that
        #: didn't pass one.
        self.temp_play_permission_source: dict[int, str] = {}

        #: Which player a `temp_play_permissions` entry's permission actually
        #: belongs to (``instance_id -> player_id``) — usually the same
        #: player whose zone was exiled from (Light Up the Stage), but not
        #: always: Ragavan, Nimble Pilferer exiles from *the player it just
        #: damaged*, yet grants the permission to Ragavan's own controller;
        #: Mnemonic Betrayal exiles an opponent's whole graveyard the same
        #: way. Set by `RulesEngine._grant_temp_play_permission` (the shared
        #: helper `exile_with_play_permission`/`exile_graveyard_with_cast_
        #: permission` both call); `GameEngine._has_temp_play_permission`
        #: checks it against the player attempting to cast/play, and
        #: `_remove_from_current_zone` searches every player's zones (not
        #: just the caster's own) so the object is actually found. Pruned in
        #: lockstep with `temp_play_permissions` at cleanup.
        self.temp_play_permission_player: dict[int, str] = {}

        #: RULE 605.1a "you may spend mana as though it were mana of any
        #: color/type" (Mnemonic Betrayal-shaped), scoped to *casting one
        #: specific exiled card* — ``instance_id -> "color" | "type"``,
        #: consulted by `RulesEngine.cast_spell`/`GameEngine.can_cast` as
        #: `ManaPool`'s own ``wildcard`` param. Set by the same shared
        #: `RulesEngine._grant_temp_play_permission` helper; pruned in
        #: lockstep with `temp_play_permissions` at cleanup (or earlier, by
        #: `ReturnRemainingExiledEffect`, once the card actually leaves
        #: exile).
        self.mana_wildcard_permission: dict[int, str] = {}

        #: RULE 702.88b Rebound's free-cast window: instance ids currently
        #: allowed to be cast *without paying their mana cost* — a sibling
        #: marker to `temp_play_permissions` rather than a cost override
        #: threaded through `ManaCost` itself, so every other `cast_spell`/
        #: `can_cast` caller is unaffected. Set by `ReboundFreeCastWindowEffect`
        #: (`game/effects.py`) when a Rebound delayed trigger fires; consumed
        #: (discarded) the instant the card is actually cast, and pruned in
        #: lockstep with `temp_play_permissions` at cleanup otherwise
        #: (`GameEngine._step_cleanup`).
        self.free_cast_instance_ids: set[int] = set()

        #: Delayed triggered abilities (RULE 603.7) a resolving spell/ability
        #: has set up to fire at a *future* step ("at the beginning of your
        #: next upkeep/main phase/end step, …" — Pacts, Mana Drain, Final
        #: Fortune, Corpse Dance). Each is a `DelayedTrigger`: its own
        #: controller, which step name fires it, whether it's scoped to that
        #: controller's step or the very next one, the live effects to put on
        #: the stack, and any baked-in targets. `GameEngine._fire_delayed_
        #: triggers` places matches on the stack at STEP_BEGIN and drops them
        #: (they fire once). Plain board state — deep-copies with `clone`.
        self.delayed_triggers: list["DelayedTrigger"] = []

        #: Recurring, bounded-duration player-scoped triggers (Nuka-Nuke
        #: Launcher's "until the end of defending player's next turn, that
        #: player gets rad counters whenever they cast a spell") — see
        #: `TemporaryPlayerTrigger`'s own docstring. Consumed by
        #: `RulesEngine._collect_temporary_player_triggers`, which also
        #: prunes expired entries. Plain board state — deep-copies with
        #: `clone`.
        self.temporary_player_triggers: list["TemporaryPlayerTrigger"] = []

        #: Extra turns to take (RULE 500.7), as a FIFO of player ids —
        #: "take an extra turn after this one" (Final Fortune, the Time Warp
        #: family) appends here; `GameEngine.begin_turn` pops the front instead
        #: of rotating the normal round-robin, so an inserted turn is taken
        #: right after the current one (and before the next player's) — RULE
        #: 500.7. Plain board state — deep-copies with `clone`.
        self.extra_turns: list[str] = []

        #: When True, the active player is asked to order their simultaneous
        #: triggered abilities (RULE 603.3b) via a `pending_choice` instead of
        #: the engine placing them in a deterministic order. Off by default so
        #: solo goldfishing stays uninterrupted; the session/UI turns it on.
        self.interactive_ordering: bool = False

        #: A layer-6 "X have '<triggered ability>'" static grant (RULE 613.7f
        #: ability-adding — Dionus, Elvish Archdruid) needs a *stable* ability
        #: instance per (granting ability, affected object) so any per-instance
        #: state (e.g. "once per turn") survives across recomputes instead of
        #: being rebuilt from scratch every pass. Keyed by
        #: ``(id(granting StaticAbility), affected instance_id)``; pruned back
        #: to only the currently-valid relationships at the end of every
        #: `continuous.recompute` pass, so a grant that stops applying just
        #: stops being cached too — no separate removal code needed. Plain
        #: cache data, not board state, so it deep-copies with everything else
        #: (`clone`) but never needs its own undo handling.
        self._granted_ability_cache: dict[tuple[int, int], Any] = {}

        #: Per-player play statistics + a flat event timeline, for the
        #: end-of-game review (cards drawn/played, mana curve, mana produced
        #: per turn, damage). Plain JSON-able data written by the engine
        #: (the rules of *what counts* stay in the engine); it lives here so
        #: it deep-copies with the state and rewinds exactly like the board.
        self.stats: dict[str, Any] = {
            "players": {
                player.id: {
                    "cards_drawn": 0,
                    "lands_played": 0,
                    "spells_cast": 0,
                    "spell_cmcs": [],
                    "mana_produced": 0,
                    "damage_dealt": 0,
                    "damage_taken": 0,
                }
                for player in players
            },
            "timeline": [],
        }

        #: The game's day/night designation (RULE 731) — ``None`` until a
        #: daybound/nightbound permanent (RULE 702.145) establishes it, then
        #: exactly one of ``"day"``/``"night"`` for the rest of the game.
        self.day_night: Optional[str] = None
        #: Spells cast by each player *this turn* (RULE 731.2's "did the
        #: active player cast any/2+ spells last turn" check) — reset for the
        #: new active player in `GameEngine.begin_turn`, incremented off the
        #: `SPELL_CAST` event by `RulesEngine._track_spell_cast`.
        self.spells_cast_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: The previous turn's active player id + their final spell count,
        #: captured by `begin_turn` right before rotating so the *next*
        #: turn's untap step can apply RULE 731.2a/2b. ``None`` on turn 1
        #: (no previous turn to check).
        self._last_turn_player_id: Optional[str] = None
        self._last_turn_spell_count: int = 0
        #: Cards drawn by each player *this turn* (RULE 121.5-adjacent "each
        #: player can't draw more than N cards each turn" cap, Spirit of the
        #: Labyrinth-shaped) — reset for the new active player in
        #: `GameEngine.begin_turn`, incremented by `RulesEngine._single_draw`
        #: on every successful draw, the same shape `spells_cast_this_turn`
        #: uses for `cast_limit`.
        self.cards_drawn_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: RULE 702.8b-adjacent "you may cast spells as though they had
        #: flash this turn" (Borne Upon a Wind-shaped) — ``{player_id: turn_
        #: number}``; a player may cast at flash speed while their entry
        #: equals the *current* `turn_number`, so this needs no cleanup-step
        #: bookkeeping (it simply stops matching once the turn advances,
        #: unlike the `temp_*` `GameObject` fields `_step_cleanup` clears).
        self.temp_flash_until_turn: dict[str, int] = {}

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

    def next_active_index(self) -> int:
        """The next player to take a turn, skipping passive dummies (UC3).

        Turn order rotates normally, but a passive "goldfish" opponent never
        becomes the active player — a solo game keeps handing the turn back
        to the human. With no non-dummy player after the current one, the
        active player is unchanged.
        """
        count = len(self.players)
        index = self.active_player_index
        for _ in range(count):
            index = (index + 1) % count
            if not self.players[index].is_dummy:
                return index
        return self.active_player_index

    def record_stat(
        self,
        player_id: str,
        kind: str,
        amount: int = 0,
        cmc: Optional[int] = None,
        name: Optional[str] = None,
    ) -> None:
        """Book one play-stat event for the end-of-game review.

        ``kind`` is one of ``"draw"``, ``"land"``, ``"spell"``, ``"mana"``,
        ``"damage_dealt"``, ``"damage_taken"``. Appends to the timeline and
        rolls the running per-player totals; unknown players (none such in
        practice) are ignored so this can never raise into a live turn.
        """
        bucket = self.stats["players"].get(player_id)
        if bucket is None:
            return
        self.stats["timeline"].append(
            {
                "turn": self.turn_number,
                "player_id": player_id,
                "kind": kind,
                "amount": amount,
                "cmc": cmc,
                "name": name,
            }
        )
        if kind == "draw":
            bucket["cards_drawn"] += amount
        elif kind == "land":
            bucket["lands_played"] += 1
        elif kind == "spell":
            bucket["spells_cast"] += 1
            if cmc is not None:
                bucket["spell_cmcs"].append(cmc)
        elif kind == "mana":
            bucket["mana_produced"] += amount
        elif kind == "damage_dealt":
            bucket["damage_dealt"] += amount
        elif kind == "damage_taken":
            bucket["damage_taken"] += amount

    def living_players(self) -> list[Player]:
        return [p for p in self.players if not p.has_lost]

    # -- Battlefield -----------------------------------------------------

    def permanents(self) -> list[GameObject]:
        """Every *live* object on the shared battlefield.

        Excludes a phased-out permanent (RULE 702.26c: "treated as though
        it doesn't exist") — still structurally in `Zone.BATTLEFIELD`
        (phasing isn't a zone change), so this is the choke point that
        makes it invisible everywhere else instead of a raw `.battlefield`
        scan. The one caller that must see a phased-out object anyway is
        `GameEngine._step_untap`'s own RULE 702.26a phase-in sweep, which
        reads `self.battlefield` directly for exactly that reason.
        """
        return [obj for obj in self.battlefield if not obj.phased_out]

    def permanents_controlled_by(self, player_id: str) -> list[GameObject]:
        return [
            obj for obj in self.battlefield
            if obj.controller_id == player_id and not obj.phased_out
        ]

    def add_to_battlefield(self, obj: GameObject) -> None:
        obj.zone = Zone.BATTLEFIELD
        # RULE 613.7b: stamp a timestamp on entry so the layer engine can order
        # multiple effects within the same layer (newest applies last).
        self._timestamp_counter = getattr(self, "_timestamp_counter", 0) + 1
        obj.timestamp = self._timestamp_counter
        # "As long as ~ entered the battlefield this turn" conditions (The
        # Wandering Emperor-shaped, `game/condition_query.py`).
        obj.turn_entered = self.turn_number
        # RULE 606.5b: a planeswalker enters with its printed starting loyalty.
        if obj.is_planeswalker and obj.card.loyalty and "loyalty" not in obj.counters:
            obj.counters["loyalty"] = obj.card.loyalty
        # RULE 714.2b: a Saga enters with a lore counter (its first chapter).
        is_entering_saga = obj.card.is_saga and not obj.is_token and "lore" not in obj.counters
        if is_entering_saga:
            obj.counters["lore"] = 1
        # RULE 716.2b: a Class enters the battlefield at class level 1.
        is_entering_class = (
            obj.card.is_class and not obj.is_token and "class_level" not in obj.counters
        )
        if is_entering_class:
            obj.counters["class_level"] = 1
        self.battlefield.append(obj)
        # Fired here (rather than left to the caller, unlike ENTERS_BATTLEFIELD)
        # so chapter I's ability triggers regardless of *how* the Saga reached
        # the battlefield (cast normally, or put there some other way) — after
        # appending, since a trigger's condition scopes by `instance_id` and
        # `_collect_triggers` only scans currently-on-battlefield objects.
        if is_entering_saga:
            self.fire_event(
                GameEvent(
                    EventType.SAGA_CHAPTER,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    controller_id=obj.controller_id,
                    chapter=1,
                )
            )
        if is_entering_class:
            self.fire_event(
                GameEvent(
                    EventType.CLASS_LEVEL,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    controller_id=obj.controller_id,
                    chapter=1,
                )
            )

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
            "day_night": self.day_night,
            "game_over": self.game_over,
            "winner_id": self.winner_id,
            "monarch_id": self.monarch_id,
            "initiative_id": self.initiative_id,
            "pending_choice": self.pending_choice,
            "temp_play_permissions": dict(self.temp_play_permissions),
            "temp_play_permission_source": dict(self.temp_play_permission_source),
            "temp_play_permission_player": dict(self.temp_play_permission_player),
            "mana_wildcard_permission": dict(self.mana_wildcard_permission),
            "free_cast_instance_ids": sorted(self.free_cast_instance_ids),
            "players": [p.to_dict() for p in self.players],
            "battlefield": [obj.to_dict() for obj in self.battlefield],
            "stack": [item.to_dict() for item in self.stack],
            "stats": self.stats,
        }

    def __repr__(self) -> str:
        return (
            f"GameState(id={self.id!r}, turn={self.turn_number}, "
            f"active={self.active_player.id!r}, step={self.current_step!r})"
        )

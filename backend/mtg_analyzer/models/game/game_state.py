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
import itertools
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .events import EventType, GameEvent
from .game_object import GameObject, Zone
from .player import Player

#: A `StackItem`'s own stable identity (RULE 115/608.2b's "target activated
#: or triggered ability" — Stifle/Trickbind-shaped, ENG-26). A spell's
#: `StackItem.obj` already has one (its `GameObject.instance_id`), but an
#: *ability* item has no such object to key off (`obj` is `None` — the
#: permanent that has the ability lives on `.source` instead, and could have
#: several of its own abilities on the stack at once). Same counter pattern
#: as `GameObject.instance_id`.
_stack_id_counter = itertools.count(1)


@dataclass
class InternalTurn:
    """The internal turn cursor and its player-facing projection.

    ``number`` advances for every player's turn (RULE 500.1). ``turn_nr``
    advances once the turn order completes a full circuit. ``player_id`` is
    the seat whose turn is currently active.
    """

    number: int = 0
    turn_nr: int = 0
    player_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "turn_nr": self.turn_nr,
            "player_id": self.player_id,
        }


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
    `docs/implementation-state/BACKLOG.md`). ``None`` (the common
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
        trigger_event: Optional[GameEvent] = None,
    ) -> None:
        self.stack_id: int = next(_stack_id_counter)
        self.kind = kind
        self.controller_id = controller_id
        self.effects = effects or []
        self.obj = obj
        self.description = description
        self.targets = targets or []
        self.target_groups = target_groups
        #: RULE 603.1: the event that *caused* this triggered ability, kept
        #: so an effect whose behaviour depends on the specific firing
        #: ("that permanent"'s produced mana, "that spell"'s card types, the
        #: player who tapped the land) can read it at resolution time. The
        #: engine exposes it as `GameContext.trigger_event` for exactly the
        #: window in which this item resolves; ``None`` for a spell or for
        #: any ability placed without one.
        self.trigger_event = trigger_event
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
            "stack_id": self.stack_id,
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
            # This item's already-chosen targets (RULE 115/601.2c), reduced to
            # bare ids — the board uses it to badge a targeted permanent and
            # to highlight a pair of stack items that target each other
            # (`gameBoardView.js`'s target-overlay feature). `self.targets`
            # holds live `GameObject`/`Player` references (see
            # `_target_instance_ids` in `casting_mixin.py`), never
            # serializable as-is.
            "targets": [
                {"instance_id": tgt.instance_id}
                if isinstance(tgt, GameObject)
                else {"player_id": tgt.id}
                for tgt in self.targets
                if isinstance(tgt, (GameObject, Player))
            ],
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
        condition: Optional[dict[str, Any]] = None,
    ) -> None:
        self.controller_id = controller_id
        self.step = step
        self.effects = effects
        self.scope = scope
        self.targets = targets or []
        self.description = description
        #: RULE 603.4 intervening-if re-checked by `GameEngine._fire_delayed_
        #: triggers` when this would go on the stack — an "…unless <X>" rider
        #: on the delayed instruction (Sauron, the Necromancer's "exile that
        #: token unless ~ is your Ring-bearer"). ``None`` (the common case)
        #: always fires. A whitelisted `EffectSpec.condition`-shaped dict.
        self.condition = condition
        #: The earliest internal turn this may fire at — 0 means "the very
        #: next matching step". Lets "at the beginning of *that* (extra) turn's
        #: end step" (Final Fortune) skip the *current* turn's end step by
        #: arming with ``min_turn = internal_turn.number + 1``.
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
        duration: str = "defending_next_turn",
        event_player_scope: str = "self",
    ) -> None:
        self.player_id = player_id
        self.event_type = event_type
        self.effects = effects
        self.install_turn = install_turn
        #: ``"defending_next_turn"`` — the Nuka-Nuke Launcher shape: arm in
        #: the ``"waiting"`` phase, go ``"active"`` when ``player_id``'s own
        #: next turn begins, drop after it ends. ``"this_turn"`` (Ruinous
        #: Waterbending's "whenever a creature dies **this turn**, you gain
        #: 1 life") — armed ``"active"`` immediately, dropped at the next
        #: `EventType.TURN_BEGIN` (anyone's).
        self.duration = duration
        #: How the installed trigger matches an event to ``player_id``:
        #: ``"self"`` — only when the event names that player (`event.get(
        #: "player_id")`, Nuka-Nuke's "whenever **they** cast a spell").
        #: ``"any"`` — fire on every matching ``event_type`` regardless of
        #: whose it is (Ruinous Waterbending's "whenever **a** creature
        #: dies"); the effects still go to ``player_id`` (baked at install).
        self.event_player_scope = event_player_scope
        self.phase = "active" if duration == "this_turn" else "waiting"
        self.active_since_turn: Optional[int] = (
            install_turn if duration == "this_turn" else None
        )
        self.description = description

    def __repr__(self) -> str:
        return (
            f"TemporaryPlayerTrigger({self.player_id} @ {self.event_type!r}, "
            f"phase={self.phase!r}, duration={self.duration!r})"
        )

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


class TurnControl:
    """MEC-51 (RULE 720): one player controls another player's **turn** — or
    just their **combat phase** — for a bounded window. "You control target
    opponent during that player's next turn." (Mindslaver, Emrakul the
    Promised End, Sorin Markov's −7, Worst Fears) / "…during their next
    combat phase." (Secret of Bloodbending).

    A small `TURN_BEGIN`-driven state machine, exactly like
    `TemporaryPlayerTrigger`:

    * ``"waiting"`` — installed; ``controlled_id``'s next turn hasn't begun
      yet (a control installed *during* the controlled player's own turn
      does not take effect until their *following* turn — RULE 720.6).
    * ``"active"`` — inside that turn. `RulesEngine._advance_turn_controls`
      flips it here at that turn's `TURN_BEGIN`. While active,
      `GameState.decider_for` / `driving_seat_for` route the controlled
      seat's decisions, priority and turn-based actions to
      ``controller_id`` (`scope == "combat"` additionally gates on the
      combat phase being current).
    * Removed at the next `TURN_BEGIN` after ``active_since_turn`` — that
      next turn beginning is what "the end of [their] turn" means here,
      the same operational definition `TemporaryPlayerTrigger` uses.

    RULE 720.x carve-outs are a **documented simplification** for this first
    cut: the controlled player still concedes for themselves (720.1), and
    "look at cards you couldn't otherwise see" (720.2) is modelled only as
    the controller seeing the controlled hand for the window
    (`services/game_session.py`), not the finer 720.3-720.7 edges. Plain
    data — deep-copies with `GameState.clone`.
    """

    def __init__(
        self,
        controlled_id: str,
        controller_id: str,
        install_turn: int,
        scope: str = "turn",
        source_name: str = "",
    ) -> None:
        self.controlled_id = controlled_id
        self.controller_id = controller_id
        self.install_turn = install_turn
        #: ``"turn"`` — the whole turn. ``"combat"`` — only while the
        #: controlled player's combat phase is the current phase.
        self.scope = scope if scope in ("turn", "combat") else "turn"
        self.source_name = source_name
        #: Emrakul, the Promised End: "After that turn, that player takes an
        #: extra turn." — `RulesEngine._advance_turn_controls` queues it onto
        #: `GameState.extra_turns` at the controlled turn's `TURN_END`.
        self.grant_extra_turn_after = False
        self.phase = "waiting"
        self.active_since_turn: Optional[int] = None

    def is_active(self, current_phase: Optional[str] = None) -> bool:
        if self.phase != "active":
            return False
        if self.scope == "combat":
            return current_phase == "combat"
        return True

    def __repr__(self) -> str:
        return (
            f"TurnControl({self.controller_id} over {self.controlled_id}, "
            f"scope={self.scope!r}, phase={self.phase!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "controlled_id": self.controlled_id,
            "controller_id": self.controller_id,
            "scope": self.scope,
            "phase": self.phase,
            "source_name": self.source_name,
        }


class GameState:
    """The full state of one game and a light event bus over it."""

    def __init__(self, players: list[Player], id: Optional[str] = None) -> None:
        if not players:
            raise ValueError("a game needs at least one player")
        self.id = id or str(uuid.uuid4())
        self.players = players

        self.internal_turn = InternalTurn()
        #: Who took turn 1 — the reference point `turn_nr` counts. Kept
        #: as an id rather than an index because players leave the game
        #: (RULE 800.4a) and the indices shift under it.
        self.starting_player_id: Optional[str] = None
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

        #: The format/variant this game is being played under
        #: (`models/game_format.py`) — its name only, so the state stays
        #: plain data; `get_format` resolves it back to the record. Decides
        #: which of the RULE 9 variant subsystems below are live at all.
        self.format_name: str = "commander"
        #: RULE 901.5: the **shared** planar deck of a Planechase game, face
        #: down but for its top card, which is the plane currently face up
        #: in the command zone (901.7). Top of the deck is the end of the
        #: list, the same convention `Player.library` uses. Empty outside a
        #: Planechase game. Per-player planar decks (also legal under 901.5)
        #: aren't modeled: one shared deck is the common table setup and the
        #: only one that needs no "whose plane is this" bookkeeping.
        self.planar_deck: list[GameObject] = []
        #: RULE 901.6b: how many times each player has rolled the planar die
        #: this turn — the die's cost is {X} where X is exactly that count,
        #: so it has to be tracked per player and reset each turn
        #: (`GameEngine.begin_turn`, alongside `lands_played_this_turn`).
        self.planar_die_rolls_this_turn: dict[str, int] = {}
        #: RULE 904.3: which player is the archenemy of an Archenemy game
        #: (the one with a scheme deck), or ``None``.
        self.archenemy_id: Optional[str] = None

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

        #: Ids of players who have left the game (conceded — RULE 104.3a)
        #: but whose objects are still on the board. Concession normally
        #: happens at sorcery speed, and yanking a board away mid-turn is
        #: disorienting for the *other* players in a multiplayer game, so
        #: `RulesEngine.concede` defers the RULE 800.4a cleanup to the start
        #: of the next player's turn (`GameEngine.begin_turn` sweeps this).
        #: With one living player left the game is over anyway and the board
        #: is simply left standing for the end-of-match review.
        self.pending_leave_ids: list[str] = []
        #: A player decision the engine is waiting on (e.g. a library
        #: search) before it can keep resolving — plain JSON-able data
        #: (kind, player_id, eligible instance ids, …) so it survives a
        #: `clone()` for rewind and serializes to the UI. None when the
        #: engine isn't blocked on a choice. Set/consumed by the rules
        #: engine (mtg_analyzer/game/rules_engine.py).
        self.pending_choice: Optional[dict[str, Any]] = None

        #: RULE 608.2: effect lists suspended mid-resolution because one of
        #: their effects opened `pending_choice`, innermost last (a LIFO
        #: stack — the most recently paused resolution finishes first).
        #: Since only one choice can be pending at a time, a resolution with
        #: 2+ interactive effects has to stop after the first and pick the
        #: rest back up once the player answers, rather than letting the
        #: second effect overwrite the first one's prompt. Each entry is the
        #: remaining effects plus the targets/`target_groups` slice they had
        #: yet to consume — pushed by `game/effects/core.py`'s
        #: `_apply_effects_partitioned`, drained by `RulesEngine.
        #: resume_deferred_effects` from `GameEngine.resolve_until_stable`.
        self.deferred_effects: list[dict[str, Any]] = []
        #: RULE 700.2 / MEC-68: modes selected by a particular triggered
        #: ability during the current turn. Keys are stable for the lifetime
        #: of a bound ability (source instance id + ability object id), and
        #: values are mode indices. `GameEngine.begin_turn` clears this at
        #: the turn boundary.
        self.trigger_mode_history: dict[tuple[str, int], set[int]] = {}

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

        #: Which `temp_play_permissions` entries carry the *shorter*,
        #: flat "until end of turn" window (Ragavan, Nimble Pilferer/
        #: Mnemonic Betrayal's own printed text) rather than the family's
        #: default "until the end of your next turn" (Light Up the Stage) —
        #: `GameEngine._step_cleanup` needs this to sweep the two windows
        #: differently (see its own comment): a same-turn-only entry is
        #: gone at the very next cleanup regardless of whose turn that is;
        #: the default one waits specifically for `temp_play_permission_
        #: player`'s own next turn to end. Pruned in lockstep with
        #: `temp_play_permissions`.
        self.temp_play_permission_same_turn_only: set[int] = set()

        #: A *standing*, condition-gated exile cast permission — ``instance_
        #: id -> (player_id, condition_dict)`` — distinct from every entry
        #: above, which all expire by turn count. "You may cast this card
        #: from exile as long as you control a Lukka planeswalker." (Lukka,
        #: Coppercoat Outcast's own +1) never expires on its own; it simply
        #: stops holding (and can start again) as `game/static_conditions.
        #: condition_holds` re-answers it live, the same `control_count`
        #: vocabulary a printed "as long as…" static already uses. Checked
        #: by `GameEngine.can_cast` alongside `temp_play_permissions`; never
        #: swept at cleanup since there's no turn window to expire.
        self.exile_cast_condition: dict[int, tuple[str, dict]] = {}

        #: RULE 701.65 (Airbend, PAR-29): instance id → a *fixed* mana-cost
        #: string ("{2}") the card's owner pays to cast it from exile
        #: **instead of** its printed mana cost, for as long as it's exiled
        #: under a matching `exile_cast_condition` grant. Read by
        #: `GameEngine.effective_cast_cost`; like `exile_cast_condition`,
        #: keyed by `instance_id` and never swept — a cast card becomes a
        #: new object (RULE 400.7) so the stale entry is inert.
        self.exile_cast_cost_override: dict[int, str] = {}

        #: RULE 702.94 Miracle (PAR-26) — instance ids of hand cards whose
        #: same-turn "cast for the miracle cost" window is currently open
        #: (the first card their controller drew this turn). Torn down at
        #: cleanup by `GameEngine._step_cleanup`; `GameEngine._offer_cast`
        #: gates the miracle-cost cast offer on membership.
        self.miracle_armed_ids: set[int] = set()

        #: RULE 701.17-adjacent "void counter" marker (Dauthi Voidwalker,
        #: MEC-42) — ``instance_id -> holder player_id`` for a card exiled
        #: by `continuous.void_counter_redirect_controller_for`'s standing
        #: redirect instead of reaching its owner's graveyard; the holder
        #: is whichever Dauthi Voidwalker's controller earned it, who may
        #: later name it in that ability's own "choose an exiled card an
        #: opponent owns with a void counter on it" activation. Never
        #: swept — a void counter, like a real counter, persists on the
        #: card for as long as it stays in exile.
        self.void_counter_holder: dict[int, str] = {}

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
        #: (`game/effects/core.py`) when a Rebound delayed trigger fires; consumed
        #: (discarded) the instant the card is actually cast, and pruned in
        #: lockstep with `temp_play_permissions` at cleanup otherwise
        #: (`GameEngine._step_cleanup`).
        self.free_cast_instance_ids: set[int] = set()

        #: "…exile the top card of each player's library, then you may
        #: cast any number of spells from among those cards without
        #: paying their mana costs." (Etali, Primal Storm/Primal Conqueror)
        #: — Scryfall's own ruling: "timing permissions based on a card's
        #: type are ignored, and the spells resolve before blockers are
        #: declared" (a mid-combat window even a sorcery-speed card must be
        #: castable in). A sibling marker to `free_cast_instance_ids`
        #: rather than a real Flash grant, so it doesn't leak into
        #: `combat.has(obj, "flash")`/anything that reads the object's own
        #: keywords. Set by `RulesEngine.grant_free_cast_window_from_exile`
        #: (``ignore_timing=True``); consulted by `GameEngine.can_cast`'s
        #: own ``sorcery_speed`` computation; pruned in lockstep with
        #: `temp_play_permissions` at cleanup, same as `free_cast_instance_
        #: ids` above.
        self.free_cast_ignore_timing_instance_ids: set[int] = set()

        #: "Target instant or sorcery card in your graveyard gains flashback
        #: until end of turn." (MEC-24 — Recoup/Snapcaster Mage/Sphinx of
        #: Forgotten Lore-shaped) — ``instance_id -> flashback cost``
        #: (a `ManaCost`-parseable string), a genuinely *per-graveyard-card*
        #: marker rather than one appended to the granting permanent's own
        #: `GameObject.static_effects` the way `GrantGraveyardCastPermission
        #: ThisTurnEffect`'s untargeted "each instant and sorcery card"
        #: sibling (Backdraft Hellkite) is: that shape reads fine off a
        #: scan of the controller's battlefield, but a *targeted* singular
        #: grant needs to survive independently of the granting permanent
        #: (which may attack, die, or leave play before the graveyard card
        #: is ever cast) and must apply to exactly one graveyard object, not
        #: every card matching a type filter. Consulted by `game/engine/
        #: casting_mixin.py`'s `_graveyard_cast_keyword`/`_flashback_cost`
        #: alongside the printed Flashback keyword; cleared unconditionally
        #: at cleanup (RULE 514.2, `GameEngine._step_cleanup`) — a flat
        #: "until end of turn" grant, unlike `temp_play_permissions`' own
        #: "until your next turn" turn-number bookkeeping.
        self.temp_flashback_grants: dict[int, str] = {}

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

        #: MEC-51 (RULE 720): active + waiting "you control that player's
        #: next turn/combat" windows. `RulesEngine._advance_turn_controls`
        #: runs the `TURN_BEGIN` state machine; `decider_for` /
        #: `driving_seat_for` below route a controlled seat's decisions to
        #: the controller while a window is `is_active`. Plain data —
        #: deep-copies with `clone`.
        self.turn_controls: list["TurnControl"] = []

        #: MEC-51b (RULE 720 / Word of Command): a resolution-scoped "you
        #: control that player" window, while the WoC caster picks a card
        #: from the target's hand and has them play it. ``{"controller_id":
        #: …, "target_id": …, "chosen_instance_id": …}`` or ``None``.
        #: `decider_for` routes the target's decisions to the controller
        #: while set; cleared once the chosen card is played. Plain dict —
        #: deep-copies with `clone`.
        self.word_of_command: Optional[dict[str, Any]] = None

        #: RULE 611 continuous effects created by a resolving spell/ability
        #: rather than by a permanent's printed static ability — "Until your
        #: next turn, creatures you control get +1/+1", "Target creature
        #: gains flying until end of combat". Each is an ordinary
        #: `game/effects/core.py` `StaticAbility` carrying a ``duration``, folded
        #: into every `continuous.recompute` exactly like a permanent's own
        #: (so it goes through the same RULE 613 layers, timestamps and
        #: dependency pass) and swept by `GameEngine` at the window its
        #: duration names (`game/durations.py`).
        #:
        #: Why these live on the *state* and not on the affected permanent
        #: (the way `temp_power`/`temp_keywords` do): RULE 611.2b — the
        #: effect exists independently of both its source and its subject, so
        #: it must survive the source leaving the battlefield, and a
        #: duration longer than the current turn has to outlive the cleanup
        #: step that clears every ``temp_*`` field. Plain data (whitelisted
        #: params + a source reference), so it deep-copies with `clone`.
        self.floating_statics: list[Any] = []

        #: RULE 615's "Damage can't be prevented this turn." (Insult //
        #: Injury/Isengard Unleashed, MEC-30) — a plain turn-scoped flag
        #: rather than a replacement effect of its own, since it has no
        #: recipient/source to key off of: it just excludes every
        #: prevention-shaped effect (`ReplacementEffect.prevents_damage`)
        #: from `RulesEngine._run_replacement_loop`'s candidate list while
        #: set. Reset at cleanup (`GameEngine._step_cleanup`), the same
        #: RULE 514.2 window every other "this turn" flag clears in.
        self.damage_prevention_disabled: bool = False

        #: MEC-46 (RULE 701.38f): "You choose how each player votes this
        #: turn." (Illusion of Choice) — the id of the player who answers
        #: *every* seat's `vote` / `vote_object` choice for the rest of the
        #: turn. `RulesEngine._advance_vote` / `_advance_object_vote`
        #: redirect the `pending_choice`'s ``player_id`` to this id while it
        #: is set (the real voter's name still rides in the prompt). Reset
        #: at cleanup (`GameEngine._step_cleanup`), the same RULE 514.2
        #: window every other "this turn" flag clears in. Plain data —
        #: deep-copies with `clone`.
        self.forced_vote_controller_id: Optional[str] = None

        #: Extra turns to take (RULE 500.7), as a FIFO of player ids —
        #: "take an extra turn after this one" (Final Fortune, the Time Warp
        #: family) appends here; `GameEngine.begin_turn` pops the front instead
        #: of rotating the normal round-robin, so an inserted turn is taken
        #: right after the current one (and before the next player's) — RULE
        #: 500.7. Plain board state — deep-copies with `clone`.
        self.extra_turns: list[str] = []

        #: RULE 500.4-adjacent "after this combat phase, there is an
        #: additional combat phase[, followed by an additional main
        #: phase]" (Combat Celebrant/Godo/World at War-shaped) — a FIFO of
        #: ``main_phase_too`` flags, mirroring `extra_turns`' own "append
        #: now, the turn loop drains it later" shape: an effect can't reach
        #: `GameEngine._turn_steps`/`_cursor` directly (only `GameContext`/
        #: `RulesEngine` are visible to it), so it queues the request here
        #: instead and `GameEngine.advance_step` drains it (via `insert_
        #: additional_combat_phase`) before running the next step. Plain
        #: board state — deep-copies with `clone`.
        self.pending_extra_combats: list[bool] = []

        #: RULE 500-adjacent "end the turn" (Day's Undoing/Time Stop-shaped
        #: reminder text) — the same "an effect can't reach `GameEngine.
        #: _turn_steps`/`_cursor` directly" shape as `pending_extra_combats`
        #: just above, but the opposite direction: instead of *inserting* a
        #: phase, `GameEngine.advance_step` drains this by fast-forwarding
        #: the cursor past every remaining step of the current turn, so its
        #: very next call rolls straight into the next turn's untap. Plain
        #: board state — deep-copies with `clone`.
        self.end_turn_requested: bool = False

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

        #: PAR-8's own identity-preservation cache, kept separate from
        #: `_granted_ability_cache` above rather than sharing it: that one's
        #: end-of-pass pruning loop only recognizes its own 2/3-element
        #: ``(id(ability), instance_id[, "activated"])`` key shapes, and
        #: would delete any other shape it finds in the same dict on every
        #: pass it doesn't also see freshly re-added first — see
        #: `continuous._apply_hand_cycling_grants`.
        self._hand_cycling_ability_cache: dict[tuple[int, int], Any] = {}

        #: MEC-21's own identity-preservation cache — "X have all activated
        #: abilities of all creature cards exiled with ~" (Agatha's Soul
        #: Cauldron) — kept separate from `_granted_ability_cache` for the
        #: same reason `_hand_cycling_ability_cache` is: its own end-of-pass
        #: pruning loop only recognizes its own 4-element ``(id(ability),
        #: grantee instance_id, exiled-card instance_id, ability index)``
        #: key shape. See `continuous._apply_borrowed_activated_abilities`.
        self._borrowed_ability_cache: dict[tuple[int, int, int, int], Any] = {}

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
        #: active player cast any/2+ spells last turn" check, and MEC-36's
        #: Damping Sphere — "costs {1} more for each **other** spell that
        #: player has cast this turn," read cross-player via `continuous.
        #: count_selector`'s ``"spells_cast_this_turn"``) — reset for
        #: *every* player each `GameEngine.begin_turn` (widened from the
        #: original RULE 731.2-only "just the incoming active player" scope
        #: once Damping Sphere needed a non-active player's own count to
        #: stay accurate too, the same `mana_produced_this_turn`/`cast_
        #: instant_or_sorcery_this_turn` game-wide idiom below), incremented
        #: off the `SPELL_CAST` event by `RulesEngine._track_spell_cast`.
        self.spells_cast_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: The greatest mana value among instant/sorcery spells each player
        #: has cast *this turn* ("…where X is the greatest mana value among
        #: instant and sorcery spells you've cast this turn." — Rootha,
        #: Mastering the Moment, PAR-60). Bumped off the `SPELL_CAST` event
        #: by `RulesEngine._track_spell_cast`, read via `continuous.
        #: count_selector`'s ``"greatest_instant_sorcery_mv_this_turn"``;
        #: reset per `GameEngine.begin_turn` alongside `spells_cast_this_turn`.
        self.greatest_instant_sorcery_mv_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Noncreature spells cast by each player *this turn* ("~ deals
        #: damage to that player equal to the number of noncreature spells
        #: they've cast this turn." — Magebane Lizard) — unlike
        #: `spells_cast_this_turn` above (reset only for the incoming
        #: active player, RULE 731.2's own narrow scope), this resets for
        #: *every* player each `GameEngine.begin_turn`, the same
        #: `mana_produced_this_turn`/`cast_instant_or_sorcery_this_turn`
        #: game-wide idiom: a non-active player's own cast still counts
        #: toward *their* running total for this trigger. Incremented
        #: alongside `spells_cast_this_turn` by `RulesEngine.
        #: _track_spell_cast`.
        self.noncreature_spells_cast_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Nonartifact spells cast by each player *this turn* ("Each player
        #: who has cast a nonartifact spell this turn can't cast additional
        #: nonartifact spells." — Ethersworn Canonist, MEC-43) — the
        #: nonartifact-scoped sibling of `noncreature_spells_cast_this_turn`
        #: above, same game-wide-every-player reset scope, incremented
        #: alongside it by `RulesEngine._track_spell_cast`.
        self.nonartifact_spells_cast_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: How many combat phases this turn has had (RULE 603.4's "if it's
        #: the first combat phase of the turn" intervening-if — Karlach,
        #: Fury of Avernus/Finest Hour/Genji Glove-shaped extra-combat
        #: guards). Incremented once per ``begin_combat`` step
        #: (`GameEngine._run_step`, game-wide, not per-player — combat has
        #: one shared count regardless of whose turn it is), reset in
        #: `GameEngine.begin_turn`.
        self.combats_this_turn: int = 0
        #: Defending players who have already submitted a `declare_blockers`
        #: action for the *current* combat (RULE 509.1a — declaring no
        #: blocks at all is itself a complete, legal answer, so an attacking
        #: player's own `obj.attacking` flag has no equivalent on the
        #: defending side: with zero blockers assigned there is no per-object
        #: state left behind to say "already answered"). Stamped by
        #: `GameEngine.declare_blockers` regardless of whether `assignments`
        #: was empty, so `legal_actions_mixin` can stop re-offering
        #: `declare_blockers` to a player who has already declared for this
        #: combat. Reset alongside every other per-combat marker in
        #: `GameEngine._clear_combat` — at `begin_turn` (before the first
        #: combat) and at `_step_end_combat` (before any extra combat phase).
        self.declared_blockers_this_combat: set[str] = set()
        #: "When you next cast an instant or sorcery spell with mana value
        #: N or less this turn, `<effect>`." (Dual Strike-shaped) — a
        #: one-shot watch for the *next* qualifying `SPELL_CAST` this turn,
        #: consumed by `RulesEngine._check_spell_watchers` (a `SPELL_CAST`
        #: subscriber, the same "one place covers every cast path" idiom
        #: `_track_spell_cast` uses) rather than a `TriggeredAbility` (which
        #: only ever fires off a *matching object's own* event) or RULE
        #: 603.7's step-scoped `DelayedTrigger` (which waits for a future
        #: *step*, not a future *event*). Each entry:
        #: ``{"controller_id", "max_mana_value", "card_types", "then_specs",
        #: "source_id", "expires_turn"}``; expired/consumed entries are
        #: dropped, never swept separately.
        self.spell_watchers: list[dict[str, Any]] = []
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
        #: Cards discarded by each player *this turn* (RULE 701.8 — "create a
        #: token that's a copy of ~ for each card you've discarded this
        #: turn", Living Laser; "draw a card for each card you've discarded
        #: this turn", Change of Fortune). Same shape/reset as `cards_drawn_
        #: this_turn` above — zeroed for the incoming active player in
        #: `GameEngine.begin_turn`, bumped at every `DISCARD_CARD` fire site
        #: (`RulesEngine.discard`/`discard_specific`, the Pitch-cost discard);
        #: read by `continuous.count_selector`'s ``"cards_discarded_this_
        #: turn"``.
        self.cards_discarded_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: "You can't attack that player this turn." (Call for Aid) —
        #: ``(attacker_player_id, defending_player_id)`` pairs barred from
        #: combat for the rest of this turn (RULE 508.1a). Checked by
        #: `GameEngine._can_attack` against the *assigned* defender only
        #: (offer-time, with no defender yet, stays permissive); cleared at
        #: cleanup (RULE 514.2).
        self.no_attack_pairs_this_turn: set[tuple[str, str]] = set()
        #: The *specific objects* drawn by each player this turn (Sylvan
        #: Library, MEC-40 — "choose two cards in your hand drawn this
        #: turn"), unlike `cards_drawn_this_turn`'s own plain count above:
        #: some effects need to name *which* cards, not just how many.
        #: Appended by `RulesEngine._single_draw`/`draw` alongside the count,
        #: reset in lockstep with it (`GameEngine.begin_turn`).
        self.cards_drawn_this_turn_ids: dict[str, list[int]] = {p.id: [] for p in players}
        #: Whether each player has already had "the first one they draw in
        #: [their] draw step" this draw step (MEC-32 — Notion Thief/Chains
        #: of Mephistopheles's shared exemption clause). Reset to ``False``
        #: for the active player only, right as their own ``"draw"`` step
        #: begins (`GameEngine._run_step`) — deliberately *not* reset by
        #: `cards_drawn_this_turn`'s own per-turn reset above, since a draw
        #: from a spell earlier in the same turn must not count as "the
        #: step's own first draw." Consulted and flipped to ``True`` by
        #: `RulesEngine._single_draw`, which only ever computes it while
        #: `current_step == "draw"` for the drawing player themself — a
        #: draw anywhere else in the turn always reads as "not first,"
        #: correctly, since it can never be the draw step's own first card.
        self.first_draw_done_this_step: dict[str, bool] = {p.id: False for p in players}
        #: Life actually gained by each player *this turn* (RULE 119.3 —
        #: "whenever ~ attacks, if you gained 3 or more life this turn,
        #: <effect>", Frodo, Adventurous Hobbit-shaped). Reset for the new
        #: active player in `GameEngine.begin_turn`, incremented by
        #: `RulesEngine.gain_life` on every successful gain — the same
        #: only-the-incoming-active-player reset `cards_drawn_this_turn`
        #: above uses, since the cards that read this are all "whenever ~
        #: attacks" triggers and a creature only ever attacks on its own
        #: controller's turn.
        self.life_gained_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Players who declared an attacker this turn (RULE 508.1a; Raid).
        #: This player history is distinct from an individual creature's
        #: Boast flag: a creature entering attacking did not declare an attack.
        self.players_attacked_this_turn: set[str] = set()
        #: The life each player has *lost* this turn — the mirror of
        #: `life_gained_this_turn`, bumped at `RulesEngine.lose_life`'s single
        #: choke point (damage, life-paid costs, "loses N life" effects all
        #: funnel through it) and reset for every player each
        #: `GameEngine.begin_turn`. Read by `ConditionalEffect`'s
        #: ``opponent_lost_life_this_turn_at_least`` key and
        #: `FaceVillainousChoiceEffect.subject_min_life_lost` (Davros, Dalek
        #: Creator — "…if an opponent lost 3 or more life this turn" / "each
        #: opponent who lost 3 or more life this turn faces a villainous
        #: choice").
        self.life_lost_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Owner ids of players who had one or more cards leave their
        #: graveyard this turn (RULE 603.3f `CARDS_LEFT_GRAVEYARD` — recorded
        #: at `RulesEngine._note_graveyard_exit`, the single zone-exit choke
        #: point, and cleared each `GameEngine.begin_turn`). Read by
        #: `static_conditions.py`'s ``card_left_graveyard_this_turn``
        #: intervening-if (Primary Research, Relic Retriever, PAR-60).
        self.cards_left_graveyard_this_turn: set[str] = set()
        #: Player ids who have already cast a spell with {X} in its mana cost
        #: this turn (PAR-60 — the Quandrix "your first spell with {X} in its
        #: mana cost each turn" trigger family: Zimone Infinite Analyst,
        #: Owlin Spiralmancer, Nev, Lattice Library). Set in
        #: `RulesEngine.cast_spell` *after* the `SPELL_CAST` event is built
        #: (whose ``first_x_spell`` flag reads this set), cleared each
        #: `GameEngine.begin_turn`.
        self.cast_x_spell_this_turn: set[str] = set()
        #: How many *nontoken* creatures each player has had enter the
        #: battlefield under their control this turn (PAR-60 — Gyome, Master
        #: Chef's "Food tokens equal to the number of nontoken creatures you
        #: had enter … this turn"). Bumped in `add_to_battlefield`, cleared
        #: each `GameEngine.begin_turn` for the incoming active player.
        self.nontoken_creatures_entered_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: PAR-60 (Zimone, All-Questioning): lands entering under each
        #: player's control this turn — a superset of ``lands_played_this_
        #: turn`` (also counts fetch/ramp puts). Reset for the active player
        #: at ``begin_turn`` like its creature sibling above.
        self.lands_entered_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Whether each player has cast an instant or sorcery spell *this
        #: turn* (PAR-10 — `game/static_conditions.py`'s
        #: ``cast_instant_or_sorcery_this_turn`` condition: Hall of Oracles/
        #: Jin-Gitaxias's activation condition, Haunting Figment/Leapfrog/
        #: Piston-Fist Cyclops's "as long as" statics). Reset for *every*
        #: player each `GameEngine.begin_turn` — like `mana_produced_this_
        #: turn` below and unlike `spells_cast_this_turn` above, since a
        #: static condition can be read for a non-active player's permanent
        #: too. Set by `RulesEngine._track_spell_cast` off the same
        #: `SPELL_CAST` event.
        self.cast_instant_or_sorcery_this_turn: dict[str, bool] = {p.id: False for p in players}
        #: Colours each player has cast a spell of *this turn* ("if an
        #: opponent has cast a blue or black spell this turn" — Veil of
        #: Summer). Same "every player, reset each `begin_turn`" scope as
        #: `cast_instant_or_sorcery_this_turn` just above (read for a
        #: non-active player too), set by `RulesEngine._track_spell_cast`
        #: off the same `SPELL_CAST` event.
        self.spell_colors_cast_this_turn: dict[str, set[str]] = {p.id: set() for p in players}
        #: Mana actually produced (tapped/hand-exiled for) by each player
        #: *this turn*, per colour (WUBRGC) — the "genutztes Potenzial" half
        #: of `game/mana_potential.py`'s open/used split. Unlike
        #: `spells_cast_this_turn`/`cards_drawn_this_turn` above (which reset
        #: only the incoming active player's entry in `begin_turn`), this
        #: resets *every* player's entry every `begin_turn` — a non-active
        #: player can still tap mana at instant speed under
        #: `GameEngine.interactive_priority` (Multiplayer), and the feature's
        #: "open + used = total capacity accessed this turn" invariant must
        #: hold for the current turn regardless of whose turn it is.
        #: Incremented by `GameEngine.tap_for_mana`/`activate_hand_mana_
        #: ability` right next to their existing `record_stat` calls.
        self.mana_produced_this_turn: dict[str, dict[str, int]] = {p.id: {} for p in players}
        #: RULE 702.8b-adjacent "you may cast spells as though they had
        #: flash this turn" (Borne Upon a Wind-shaped) — ``{player_id: turn_
        #: number}``; a player may cast at flash speed while their entry
        #: equals the *current* internal turn, so this needs no cleanup-step
        #: bookkeeping (it simply stops matching once the turn advances,
        #: unlike the `temp_*` `GameObject` fields `_step_cleanup` clears).
        self.temp_flash_until_turn: dict[str, int] = {}
        #: RULE 116.2a-adjacent (MEC-35, Leonin Arbiter): "Any player may
        #: pay {2} for that player to ignore this effect until end of
        #: turn." — ``{player_id: internal_turn.number}``, the same "stops matching
        #: once the turn advances, no cleanup bookkeeping" shape as
        #: `temp_flash_until_turn` right above. Consulted by
        #: `RulesEngine._has_search_exemption`, which every `request_
        #: search` prohibition check now also allows past; set by
        #: `GameEngine.pay_search_exemption` (a genuine RULE 116.2a special
        #: action — no stack, offered any time the payer has priority).
        self.search_exempt_until_turn: dict[str, int] = {}
        #: Who each source has dealt *combat* damage to this turn (RULE
        #: 120.3): ``{source instance_id: {player_id, …}}``, stamped by
        #: `RulesEngine.deal_damage` and cleared for the whole game in
        #: `GameEngine.begin_turn`. Exists because "target player who was
        #: dealt combat damage by ~ this turn" (Hope of Ghirapur) is a
        #: *history* question no live board state can answer — by the time
        #: the sacrifice ability is activated, the damage step is long over.
        #: Keyed by source rather than by player so two copies of the same
        #: card each track their own victims.
        self.combat_damage_to_players_this_turn: dict[int, set[str]] = {}
        #: Total *noncombat* damage each player has dealt to opponents
        #: *this turn* ("This spell costs {X} less to cast, where X is the
        #: total amount of noncombat damage dealt to your opponents this
        #: turn." — Chandra's Incinerator, MEC-45): ``{dealing player_id:
        #: summed amount}`` — an amount total, unlike
        #: `combat_damage_to_players_this_turn`'s own per-source hit-*set*
        #: (RULE 120.3 only ever asks "was this player hit", never "how
        #: much"). Incremented by `RulesEngine.deal_damage`, reset
        #: game-wide in `GameEngine.begin_turn`.
        self.noncombat_damage_to_opponents_this_turn: dict[str, int] = {}
        #: Total damage (combat *and* noncombat, from *any* source) dealt
        #: to each player *this turn* — ``{player_id: summed amount}``
        #: (Final Punishment, MEC-43: "loses life equal to the damage
        #: already dealt to that player this turn"). Unlike
        #: `noncombat_damage_to_opponents_this_turn` (keyed by the
        #: *dealing* player, noncombat only, opponents only) and
        #: `combat_damage_to_players_this_turn` (a per-source hit-*set*,
        #: combat only), this is the plain RULE 120.3 total a *victim*
        #: took, from anyone, by any means — the simplest of the three, but
        #: no prior card needed exactly this reading. Incremented by
        #: `RulesEngine.deal_damage`, reset game-wide in `GameEngine.
        #: begin_turn`.
        self.damage_dealt_to_players_this_turn: dict[str, int] = {}
        #: PAR-32: total damage dealt *by* each player's own sources this
        #: turn, ``{controller_id: amount}`` (Dragon Cultist — "if a source
        #: you controlled dealt N or more damage this turn"). Incremented in
        #: `RulesEngine.deal_damage` off ``source.controller_id``, cleared
        #: game-wide in `begin_turn`.
        self.damage_dealt_by_this_turn: dict[str, int] = {}
        #: PAR-32: player ids into whose graveyard a *creature card* went
        #: from anywhere this turn (Cloakwood Hermit). Added in
        #: `RulesEngine._move_to_graveyard` (and mill/discard paths), keyed
        #: by the card's owner; cleared game-wide in `begin_turn`.
        self.creature_card_to_graveyard_this_turn: set[str] = set()
        #: RULE 702.175 (Descend): player ids for whom a permanent card was
        #: put into their graveyard from anywhere this turn.  Unlike the
        #: creature-only history above, this includes artifact/enchantment/
        #: land/planeswalker cards as well.
        self.permanent_card_to_graveyard_this_turn: set[str] = set()
        #: MEC-57: player ids whose "the first time you would draw a card
        #: each turn, instead …" replacement (Scion of Halaster) has already
        #: fired this turn — the gate `effects._first_draw_look_two_
        #: replacement` reads/sets, distinct from `Player.first_draw_done_
        #: this_step` (which resets every *draw step*, not every turn).
        #: Cleared game-wide in `GameEngine.begin_turn`.
        self.first_draw_replaced_this_turn: set[str] = set()
        #: MEC-60: each player's own creature-*subtype* words (lowercase)
        #: among every spell they've cast this turn — ``{player_id:
        #: {subtype, ...}}`` — the general "have you cast a `<subtype>`
        #: spell yet this turn" tracker `static_conditions`'
        #: ``first_subtype_spell_this_turn`` reads (Acolyte of Bahamut:
        #: "The first Dragon spell you cast each turn costs {2} less").
        #: Populated in `RulesEngine._track_spell_cast` off the just-cast
        #: object's live subtypes (not the SPELL_CAST event's own
        #: ``object_types``, which only carries *main* card types); cleared
        #: game-wide in `GameEngine.begin_turn`.
        self.creature_type_spells_cast_this_turn: dict[str, set[str]] = {}
        #: How many creatures have died under each player's control *this
        #: turn* (RULE 700.4) — ``{player_id: count}``, incremented off the
        #: `DIES` event by `RulesEngine._track_creature_death` and cleared
        #: wholesale in `GameEngine.begin_turn`, the same shape
        #: `spells_cast_this_turn` uses. Exists because "unless a creature
        #: died under your control this turn" (Bontu the Glorified's attack
        #: restriction) is a *history* question — the creature is long gone
        #: from every zone a live board scan could reach.
        self.creatures_died_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: Intermediate Chirography (PAR-60), level 3: "if a **modified**
        #: creature died under your control this turn". Same `DIES`-subscribed,
        #: begin-turn-cleared, controller-keyed shape as
        #: `creatures_died_this_turn` above. Documented simplification:
        #: "modified" is read as "had one or more counters" (RULE 700.9's
        #: Equipment/Aura modifications are not tracked here), off the DIES
        #: event's snapshotted ``counters``.
        self.modified_creatures_died_this_turn: dict[str, int] = {p.id: 0 for p in players}
        #: MEC-49: for each creature that took damage *this turn*, the set of
        #: `instance_id`s of the sources that dealt it — ``{damaged_obj_id:
        #: {source_id, …}}``. A *history* question no live board can answer:
        #: "whenever a creature dealt damage by ~ this turn dies, …" (Baron
        #: Sengir, Abattoir Ghoul, Blood Cultist &c.) is asked off the DIES
        #: event, after the creature is gone. Recorded by `RulesEngine.
        #: deal_damage` for any damage to a creature (combat *or* not, from
        #: any source), read by `effect_binder._build_group_ok`'s
        #: ``damaged_by_source_this_turn`` filter, cleared wholesale in
        #: `GameEngine.begin_turn` (the per-source hit-*set* sibling of
        #: `combat_damage_to_players_this_turn`).
        self.creatures_damaged_by_source_this_turn: dict[int, set[int]] = {}

        #: Player ids granted "you have no maximum hand size **for the rest
        #: of the game**" by a resolving spell/ability (Spirit Water
        #: Revival) — the durational, resolve-time-granted sibling of the
        #: battlefield-static `no_max_hand_size` layer (Reliquary Tower).
        #: Consulted by `continuous.has_no_maximum_hand_size`; never
        #: cleared (rest of the game), and RULE 400.7-safe (keyed by the
        #: player, not an object).
        self.no_max_hand_size_player_ids: set[str] = set()

        #: Which bending keyword actions (RULE 701.6x — Avatar: The Last
        #: Airbender) each player has performed *this turn*: ``{player_id:
        #: {"waterbend", "earthbend", "firebend", "airbend"}}``. Populated by
        #: `RulesEngine.record_bend` (which also fires `EventType.BENT`) and
        #: cleared wholesale in `GameEngine.begin_turn`, the same
        #: history-question shape `creatures_died_this_turn` uses above —
        #: Avatar Aang's "then if you've done all four this turn, transform"
        #: is exactly such a question (the individual bends leave no board
        #: trace a live scan could reach).
        self.bends_this_turn: dict[str, set[str]] = {}

        #: Player ids who have put one or more counters on a creature *this
        #: turn* — "At the beginning of each end step, if you put a counter
        #: on a creature this turn, …" (Lasting Tarfire). Populated in
        #: `RulesEngine.add_counters`'s post-replacement `_finish` (keyed by
        #: the COUNTER event's causer-scoped ``source_controller_id``) and
        #: cleared wholesale in `GameEngine.begin_turn`, the same game-wide
        #: history-question shape `bends_this_turn` / `creatures_died_this_turn`
        #: use above.
        self.counter_placed_on_creature_this_turn: set[str] = set()

        #: Chronological log of everything fired; also the record the
        #: WebSocket layer can diff to build ``game_state_update``s.
        self.event_log: list[GameEvent] = []
        #: Observer callbacks invoked for every fired event.
        self._subscribers: list[Callable[[GameEvent], None]] = []

    # -- Players ---------------------------------------------------------

    @property
    def turn_nr(self) -> int:
        return self.internal_turn.turn_nr

    @turn_nr.setter
    def turn_nr(self, value: int) -> None:
        self.internal_turn.turn_nr = int(value)

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

    def find_object(self, instance_id: int) -> Optional[Any]:
        """Locate a game object by its instance id across every zone.

        Lets an action referencing an object by id (as `legal_actions`
        reports it) be resolved back to the live `GameObject`, which is
        essential after a rewind swaps in a fresh copy of the state. Also
        finds a `models.game.emblem.Emblem` (RULE 114.4's own activated ability,
        MEC-8) — the two never collide since `Emblem.instance_id` shares
        `GameObject`'s own counter.
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
        for player in self.players:
            # RULE 114.4: an emblem's own activated ability (MEC-8) round-trips
            # through `legal_actions`/`activate_ability` by `instance_id` the
            # same way a permanent's does — see `models/emblem.py`.
            for emblem in player.emblems:
                if emblem.instance_id == instance_id:
                    return emblem
        return None

    def non_active_players(self) -> list[Player]:
        return [p for i, p in enumerate(self.players) if i != self.active_player_index]

    # --- MEC-51: turn control (RULE 720) ------------------------------------

    def active_turn_control_for(self, player_id: str) -> Optional["TurnControl"]:
        """The `TurnControl` currently steering ``player_id``'s decisions —
        an ``"active"`` window whose ``scope`` matches the current phase — or
        ``None``. If two are somehow active (a second effect layered on),
        the most recently installed wins (RULE 720.6-adjacent last-one)."""
        live = {p.id for p in self.players if not p.has_lost}
        matches = [
            tc for tc in self.turn_controls
            if tc.controlled_id == player_id
            and tc.controller_id in live
            and tc.is_active(self.current_phase)
        ]
        return max(matches, key=lambda tc: tc.install_turn, default=None)

    def decider_for(self, player_id: str) -> str:
        """Who actually makes ``player_id``'s decisions right now — the
        controller of an active `TurnControl` over them (MEC-51), or the
        controller of an in-progress Word of Command (MEC-51b), else
        themselves. The one routing chokepoint every caller (`game_session`
        dispatch / view / choice redaction, `RulesEngine` turn-based
        actions) goes through."""
        woc = self.word_of_command
        if woc is not None and woc.get("target_id") == player_id:
            return woc.get("controller_id") or player_id
        tc = self.active_turn_control_for(player_id)
        return tc.controller_id if tc is not None else player_id

    def driving_seat_for(self, actor_id: str) -> Optional[str]:
        """The controlled seat ``actor_id`` is currently entitled to drive
        (the inverse of `decider_for`), or ``None`` — used to let a
        controller's action arrive *as* the controlled player."""
        for tc in self.turn_controls:
            if tc.controller_id == actor_id and tc.is_active(self.current_phase):
                return tc.controlled_id
        return None

    def sync_turn_nr(self) -> None:
        """Re-derive ``turn_nr`` from the internal turn for a board set outright.

        Replay/Puzzle positions and the `edit_set_turn` action assign a turn
        number directly instead of reaching it by playing, so there was no
        wrap around the table for `GameEngine._advance_turn_nr` to
        count. Derived from how many seats actually take turns (the goldfish
        dummy never does), which makes a solo board's round equal its turn.
        """
        seats = max(1, len([p for p in self.players if not p.is_dummy]))
        self.turn_nr = max(1, -(-max(1, self.internal_turn.number) // seats))
        if self.starting_player_id is None and self.players:
            self.starting_player_id = self.players[0].id

    def next_active_index(self) -> int:
        """The next player to take a turn, skipping passive dummies (UC3).

        Turn order rotates normally, but a passive "goldfish" opponent never
        becomes the active player — a solo game keeps handing the turn back
        to the human. A player who has left the game (RULE 104.3a: lost or
        conceded) is skipped for the same reason. With no eligible player
        after the current one, the active player is unchanged.
        """
        count = len(self.players)
        index = self.active_player_index
        for _ in range(count):
            index = (index + 1) % count
            if not self.players[index].is_dummy and not self.players[index].has_lost:
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
                "turn": self.turn_nr,
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

    def next_timestamp(self) -> int:
        """A fresh, strictly-increasing RULE 613.7b timestamp.

        `add_to_battlefield` uses this for a permanent's own entry
        timestamp; `effects.GrantUntilEffect` (MEC-43 round 4E) uses the
        same counter to stamp a *resolving effect's own* continuous grant
        the moment it's created — distinct from (and, for a grant that
        outlives a fast-changing board, often later than) whatever
        permanent it happens to affect. Without this, `game/continuous.
        _in_layer`'s ordering fell back to the affected object's own
        `GameObject.timestamp`, which is wrong whenever a grant is created
        well after that object entered the battlefield (Swift
        Reconfiguration's granted Crew ability, activated long after both
        the enchanted creature and the Aura itself already exist, must
        still apply *after* the Aura's own "loses all other card types"
        layer-4 static, not before it).
        """
        self._timestamp_counter = getattr(self, "_timestamp_counter", 0) + 1
        return self._timestamp_counter

    def add_to_battlefield(self, obj: GameObject, *, saga_lore_override: Optional[int] = None) -> None:
        """``saga_lore_override``, when given, is RULE 702.155b/714.3b's Read
        Ahead entry count instead of the ordinary single lore counter —
        `RulesEngine._offer_read_ahead`/`_resolve_permanent_spell`'s own
        continuation is the only caller that ever passes it, having already
        interactively asked the controller. RULE 702.155a: only the chapter
        ability whose number *exactly* matches the entry count fires (a
        single `SAGA_CHAPTER` event carrying that count) — any lower chapter
        is skipped for good, not merely delayed, so this must never fire the
        default chapter-1 event and then "catch up" separately.
        """
        obj.zone = Zone.BATTLEFIELD
        # RULE 613.7b: stamp a timestamp on entry so the layer engine can order
        # multiple effects within the same layer (newest applies last).
        obj.timestamp = self.next_timestamp()
        # "As long as ~ entered the battlefield this turn" conditions (The
        # Wandering Emperor-shaped, `game/condition_query.py`).
        obj.turn_entered = self.internal_turn.number
        # PAR-60 (Gyome, Master Chef): count nontoken creatures entering
        # under each player's control this turn.
        if obj.is_creature and not obj.is_token:
            _entrant = obj.controller_id or obj.owner_id
            if _entrant is not None:
                self.nontoken_creatures_entered_this_turn[_entrant] = (
                    self.nontoken_creatures_entered_this_turn.get(_entrant, 0) + 1
                )
        # PAR-60 (Zimone, All-Questioning): "if a land entered the
        # battlefield under your control this turn …".
        if obj.is_land:
            _lentrant = obj.controller_id or obj.owner_id
            if _lentrant is not None:
                self.lands_entered_this_turn[_lentrant] = (
                    self.lands_entered_this_turn.get(_lentrant, 0) + 1
                )
        # RULE 606.5b: a planeswalker enters with its printed starting loyalty.
        if obj.is_planeswalker and obj.card.loyalty and "loyalty" not in obj.counters:
            obj.counters["loyalty"] = obj.card.loyalty
        # RULE 310.4b: a battle enters with defense counters equal to its
        # printed defense — the same shape as loyalty above, and seeded at
        # the same choke point so *every* way a battle reaches the
        # battlefield (cast, reanimated, or placed by the Replay editor)
        # gets them, not just the cast path.
        if obj.is_battle and obj.card.defense and "defense" not in obj.counters:
            obj.counters["defense"] = obj.card.defense
        # RULE 714.2b/714.3b: a Saga enters with a lore counter (its first
        # chapter) — or, with Read Ahead, the controller's chosen count.
        is_entering_saga = obj.card.is_saga and not obj.is_token and "lore" not in obj.counters
        if is_entering_saga:
            obj.counters["lore"] = saga_lore_override if saga_lore_override is not None else 1
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
                    chapter=obj.counters["lore"],
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
        # RULE 708.9: "if a face-down permanent moves from the battlefield to
        # any other zone, its owner must reveal it to all players as they
        # move it" — so no object ever leaves the battlefield still wearing
        # the synthetic 2/2 face. Done here, at the one chokepoint every
        # departure goes through (graveyard, exile, hand, library, the
        # command zone), rather than at each caller. Deliberately the bare
        # model transition, never `RulesEngine.turn_face_up`: this reveal
        # fires no "turned face up" trigger (RULE 701.40g's wording for the
        # analogous case) and charges no cost.
        obj.turn_face_up()

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
        self.internal_turn.player_id = self.active_player.id
        return {
            "id": self.id,
            "internal_turn": self.internal_turn.to_dict(),
            "turn_nr": self.turn_nr,
            # Legacy wire fields remain during the client migration. New
            # consumers should use `internal_turn` and `turn_nr`.
            "internal_turn": self.internal_turn.to_dict(),
            "turn_nr": self.turn_nr,
            "active_player_id": self.active_player.id,
            "priority_player_id": self.priority_player.id if self.priority_player else None,
            "current_phase": self.current_phase,
            "current_step": self.current_step,
            "day_night": self.day_night,
            "game_over": self.game_over,
            "winner_id": self.winner_id,
            "monarch_id": self.monarch_id,
            "initiative_id": self.initiative_id,
            # RULE 8/9: the format, and the Planechase state the board shows —
            # the face-up plane (901.7) plus how many planes are left behind
            # it. The rest of the planar deck is face down, so only its size
            # ships, exactly like a library's.
            "format": self.format_name,
            "archenemy_id": self.archenemy_id,
            "active_plane": (
                self.planar_deck[-1].to_dict() if self.planar_deck else None
            ),
            "planar_deck_count": len(self.planar_deck),
            "pending_choice": self.pending_choice,
            # MEC-51 (RULE 720): active/waiting "you control that player's
            # turn/combat" windows, for the board's control banner.
            "turn_controls": [tc.to_dict() for tc in self.turn_controls],
            # MEC-51b: an in-progress Word of Command (controller_id /
            # target_id), for the board's "you are playing a card from X's
            # hand" banner.
            "word_of_command": dict(self.word_of_command) if self.word_of_command else None,
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
            f"GameState(id={self.id!r}, turn={self.internal_turn.number}, "
            f"active={self.active_player.id!r}, step={self.current_step!r})"
        )

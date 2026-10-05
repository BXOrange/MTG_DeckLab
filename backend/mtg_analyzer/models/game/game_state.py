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
from contextlib import contextmanager
import itertools
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from . import turn_history
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
        ability_key: Optional[str] = None,
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
        #: Which ability of ``source`` this item is, for the per-ability
        #: resolution count ("the second time this ability has resolved this
        #: turn" — `GameObject.ability_resolutions`). The ability's printed
        #: text: stable across the undo deep copy (an ``id()`` would not be)
        #: and distinct between an object's different abilities. ``None`` for
        #: a spell, or an ability placed without one (it simply isn't counted).
        self.ability_key = ability_key

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


class UncounterableGrant:
    """A continuous effect of a resolved spell or ability: for the rest of the turn the
    controller's spells (optionally only those of ``card_types``) can't be countered
    (RULE 101.2 — "can't" beats "can", RULE 611.2a — it lasts a fixed time).

    This is a *rule*, not a trigger: it applies to a spell already on the stack when the
    effect resolves and to every one cast afterwards, and an opponent has no window to
    respond to it — which a trigger on the cast event would have given them.
    ``next_only`` is the "the next spell you cast" variant: it protects the first
    qualifying spell cast after ``casts_before`` (the controller's cast count when the
    effect resolved, read from the turn's own `SPELL_CAST` events), so nothing has to
    watch for that cast. Deep-copies with `GameState.clone`.
    """

    def __init__(
        self,
        controller_id: str,
        turn: int,
        card_types: Optional[list[str]] = None,
        next_only: bool = False,
        casts_before: int = 0,
    ) -> None:
        self.controller_id = controller_id
        self.turn = turn
        self.card_types = list(card_types) if card_types else None
        self.next_only = bool(next_only)
        self.casts_before = int(casts_before)

    def __repr__(self) -> str:
        return (f"UncounterableGrant({self.controller_id}, turn={self.turn}, "
                f"types={self.card_types}, next_only={self.next_only})")


class TurnScopedTrigger:
    """A triggered ability that a resolving spell or ability creates and that lasts
    the rest of the turn (RULE 603.7a — "whenever a creature enters this turn, draw a
    card.", "until end of turn, whenever a player casts an instant or sorcery spell,
    …"). Unlike a permanent's ability its ``source`` (the spell) is not on the
    battlefield, so `RulesEngine._collect_turn_scoped_triggers` scans this list
    alongside the permanents. ``ability`` is a fully bound `TriggeredAbility`;
    ``install_turn`` is the internal turn it was created in — it is dropped as soon as
    that is no longer the current turn. ``once`` is the "the next time" variant
    ("when you next cast an instant or sorcery spell this turn"): it fires once and is
    removed. Deep-copies with `GameState.clone`.
    """

    def __init__(self, ability: Any, install_turn: int, once: bool = False) -> None:
        self.ability = ability
        self.install_turn = install_turn
        self.once = once

    def __repr__(self) -> str:
        return f"TurnScopedTrigger(turn={self.install_turn}, once={self.once}, {self.ability.description!r})"


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
        return (
            f"TemporaryPlayerTrigger({self.player_id} @ {self.event_type!r}, "
            f"phase={self.phase!r})"
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
        # Resolve-time payment frame belongs to state so rewind preserves it.
        self.pending_pay_cost_then: Optional[dict[str, Any]] = None
        # RULE 608.2g: scoped permission while a resolving effect offers
        # playing a card; separate from pending_choice while casting it.
        self.resolution_play_choice: Optional[dict[str, Any]] = None
        self.resolution_play_followup: Optional[dict[str, Any]] = None
        self.resolution_play_waiting = False

        #: RULE 701.30c: cards currently revealed by a clash.  These are
        #: public information even though they remain in normally hidden
        #: libraries, so `to_dict` emits their faces separately until every
        #: clashing player has decided whether to put theirs on the bottom.
        #: Instance ids keep snapshots/rewind independent of live objects.
        self.clash_revealed: list[int] = []

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
        #: Single-card normal-cost graveyard permissions, cleared on casting and cleanup.
        self.temp_graveyard_cast_permissions: dict[int, str] = {}
        #: Cards whose graveyard cast permission (above) also forbids their caster any further spells that turn
        #: ("If you do, you can't cast additional spells this turn." — Conduit of Worlds), and the players whose
        #: casting that has locked. Both cleared at cleanup.
        self.cast_lock_instance_ids: set[int] = set()
        self.no_more_spells_this_turn: set[str] = set()

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

        #: Triggered abilities a resolving spell/ability created for the rest of the
        #: turn (PAR-124) — see `TurnScopedTrigger`. Scanned by
        #: `RulesEngine._collect_turn_scoped_triggers`, which also prunes the expired.
        self.turn_scoped_triggers: list["TurnScopedTrigger"] = []

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

        #: RULE 601.2f discounts that last "this turn" and belong to a player,
        #: not a permanent: "spells you cast this turn that are black and/or
        #: red cost {X} less" (Rowan, Scion of War), "the next spell you cast
        #: this turn costs {1} less" (Hardened Berserker). Each entry is plain
        #: data — ``player_id``, ``amount``, optional ``spell_type``/
        #: ``spell_colors``/``face_down`` filters, ``next_only`` and a
        #: ``source`` name — read by `continuous.cost_reduction_for`; a
        #: ``next_only`` entry is used up by the next matching cast. Reset at
        #: cleanup (`GameEngine._step_cleanup`, RULE 514.2).
        self.turn_cost_reductions: list[dict[str, Any]] = []

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
        #: "Spells you control can't be countered this turn." / "The next spell you cast this
        #: turn can't be countered." (Veil of Summer, Domri, Mistrise Village) — see
        #: `UncounterableGrant`. Read by `RulesEngine._is_cant_be_countered`; a grant of an
        #: earlier turn is ignored there and dropped when the next one is added.
        self.uncounterable_grants: list["UncounterableGrant"] = []
        #: The previous turn's active player id + their final spell count,
        #: captured by `begin_turn` right before rotating so the *next*
        #: turn's untap step can apply RULE 731.2a/2b. ``None`` on turn 1
        #: (no previous turn to check).
        self._last_turn_player_id: Optional[str] = None
        self._last_turn_spell_count: int = 0
        #: "You can't attack that player this turn." (Call for Aid) —
        #: ``(attacker_player_id, defending_player_id)`` pairs barred from
        #: combat for the rest of this turn (RULE 508.1a). Checked by
        #: `GameEngine._can_attack` against the *assigned* defender only
        #: (offer-time, with no defender yet, stays permissive); cleared at
        #: cleanup (RULE 514.2).
        self.no_attack_pairs_this_turn: set[tuple[str, str]] = set()
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
        #: Owner ids of players who had one or more cards leave their
        #: graveyard this turn (RULE 603.3f `CARDS_LEFT_GRAVEYARD` — recorded
        #: at `RulesEngine._note_graveyard_exit`, the single zone-exit choke
        #: point, and cleared each `GameEngine.begin_turn`). Read by
        #: `static_conditions.py`'s ``card_left_graveyard_this_turn``
        #: intervening-if (Primary Research, Relic Retriever, PAR-60).
        self.cards_left_graveyard_this_turn: set[str] = set()
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
        #: PAR-124: "You may cast **sorcery** spells this turn as though
        #: they had flash." (Complete the Circuit) — the type-scoped sibling
        #: of `temp_flash_until_turn` just above; kept as a separate field
        #: rather than widening that one's value shape, since every existing
        #: reader/writer of the unrestricted grant would otherwise need to
        #: learn a new tuple shape for a case that never applies to them.
        #: ``{player_id: (turn_number, (type_word, ...))}``.
        self.temp_flash_until_turn_types: dict[str, tuple[int, tuple[str, ...]]] = {}
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
        #: MEC-57: player ids whose "the first time you would draw a card
        #: each turn, instead …" replacement (Scion of Halaster) has already
        #: fired this turn — the gate `effects._first_draw_look_two_
        #: replacement` reads/sets, distinct from `Player.first_draw_done_
        #: this_step` (which resets every *draw step*, not every turn).
        #: Cleared game-wide in `GameEngine.begin_turn`.
        self.first_draw_replaced_this_turn: set[str] = set()

        #: Player ids granted "you have no maximum hand size **for the rest
        #: of the game**" by a resolving spell/ability (Spirit Water
        #: Revival) — the durational, resolve-time-granted sibling of the
        #: battlefield-static `no_max_hand_size` layer (Reliquary Tower).
        #: Consulted by `continuous.has_no_maximum_hand_size`; never
        #: cleared (rest of the game), and RULE 400.7-safe (keyed by the
        #: player, not an object).
        self.no_max_hand_size_player_ids: set[str] = set()



        #: Chronological log of everything fired; also the record the
        #: WebSocket layer can diff to build ``game_state_update``s.
        self.event_log: list[GameEvent] = []
        #: Observer callbacks invoked for every fired event.
        self._subscribers: list[Callable[[GameEvent], None]] = []
        #: RULE 603.2c simultaneity scope (`simultaneous`): nesting depth, and the
        #: batched per-object events fired inside it, flushed as `EVENT_BATCH`es.
        self._batch_depth: int = 0
        self._batch_buffer: list[GameEvent] = []
        #: Held open across an interactive multi-pick (`hold_batches`): the picks of one
        #: "sacrifice two creatures" / "discard two cards" are one event, answered one
        #: pick at a time.
        self._batch_hold: bool = False
        #: RULE 603.3f: the cards that left a graveyard inside the open scope — one
        #: `CARDS_LEFT_GRAVEYARD` names them all when it closes (`note_graveyard_exit`).
        self._graveyard_exits: list[dict[str, Any]] = []

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

    def living_players_apnap(self) -> list[Player]:
        """Living seats in order starting with the active player (RULE 101.4)."""
        seats = self.players[self.active_player_index:] + self.players[:self.active_player_index]
        return [player for player in seats if not player.has_lost]

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
        # RULE 731.1: this entry replacement establishes day only while
        # neither designation exists, before the entrant is on the field.
        if getattr(obj, "establishes_day_on_entry", False) and self.day_night is None:
            self.day_night = "day"
        obj.zone = Zone.BATTLEFIELD
        # RULE 613.7b: stamp a timestamp on entry so the layer engine can order
        # multiple effects within the same layer (newest applies last).
        obj.timestamp = self.next_timestamp()
        # "As long as ~ entered the battlefield this turn" conditions (The
        # Wandering Emperor-shaped, `game/condition_query.py`).
        obj.turn_entered = self.internal_turn.number
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
        # RULE 400.7: the new object has not paid this permanent's blitz cost.
        # Departure events have already captured its last-known abilities.
        obj.blitz_cost_paid = False
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

        Event subscribers (bound methods of a live `RulesEngine`) are
        intentionally *not* copied: the clone is inert game data, and whoever
        restores it wraps a fresh engine around it that re-subscribes. The event
        log retains the current turn and earlier turn/attack events, needed
        for conditions referring to each opponent's own most recent turn.
        Because the underlying `Card` definitions are
        immutable and share via ``Card.__deepcopy__``, and `GameObject`
        instance ids are plain values, all in-state references (an object
        on the battlefield vs. referenced from the stack) stay consistent
        across the copy.
        """
        subscribers, log = self._subscribers, self.event_log
        turn = self.internal_turn.number
        self._subscribers, self.event_log = [], [
            e for e in log
            if e.turn == turn or e.type in (EventType.TURN_BEGIN, EventType.ATTACKS)
        ]
        try:
            clone = copy.deepcopy(self)
        finally:
            self._subscribers, self.event_log = subscribers, log
        return clone

    #: Per-object events a "one or more" / "N or more" trigger counts (RULE 603.2c).
    BATCHED_EVENT_TYPES: frozenset[str] = frozenset({
        EventType.ENTERS_BATTLEFIELD, EventType.LEAVES_BATTLEFIELD, EventType.DIES,
        EventType.DISCARD_CARD, EventType.PUT_INTO_GRAVEYARD, EventType.SACRIFICE,
    })

    @contextmanager
    def simultaneous(self) -> "Iterator[None]":
        """Everything fired inside happens at once (RULE 603.2c / 704.3).

        Batched per-object events (`BATCHED_EVENT_TYPES`) are collected and, when the
        outermost scope closes, re-announced as one `EVENT_BATCH` per type. Nested
        scopes merge into the outermost; an event fired outside every scope is its own
        one-member batch (`fire_event`).
        """
        self._batch_depth = getattr(self, "_batch_depth", 0) + 1
        try:
            yield
        finally:
            if self._batch_depth == 1 and not getattr(self, "_batch_hold", False):
                # Still inside the scope, so the arrivals join this batch.
                self.announce_graveyard_arrivals()
            self._batch_depth -= 1
            if self._batch_depth == 0 and not getattr(self, "_batch_hold", False):
                self._flush_batches()

    def _zone_map(self) -> dict[int, tuple[str, str]]:
        """Every card's current zone, as ``instance_id → (zone, owner id)``."""
        where: dict[int, tuple[str, str]] = {}
        for obj in self.battlefield:
            where[obj.instance_id] = ("battlefield", obj.owner_id)
        for item in self.stack:
            if getattr(item, "obj", None) is not None:
                where[item.obj.instance_id] = ("stack", item.obj.owner_id)
        for player in self.players:
            for zone, objects in player.zones.items():
                for obj in objects:
                    where[obj.instance_id] = (str(getattr(zone, "value", zone)), player.id)
        return where

    def announce_graveyard_arrivals(self) -> None:
        """Fire `PUT_INTO_GRAVEYARD` for each card that reached a graveyard since the last check.

        RULE 603.2/603.3: a trigger condition is met when the event happens, and the
        ability goes on the stack the next time a player would receive priority. Every
        instruction and every SBA sweep closes a `simultaneous` scope, so checking there
        sees each arrival before anyone gets priority, whichever of the engine's many
        graveyard writes made it. The first check only takes the baseline.
        """
        now = self._zone_map()
        before = getattr(self, "_zones_seen", None)
        self._zones_seen = now
        if before is None:
            return
        for player in self.players:
            for obj in player.graveyard:
                was = before.get(obj.instance_id)
                if was is not None and was[0] == "graveyard":
                    continue
                # RULE 108.4a: a card in a graveyard has no controller — its owner answers
                # for it, not whoever last controlled the permanent.
                obj.controller_id = player.id
                self.fire_event(GameEvent(
                    EventType.PUT_INTO_GRAVEYARD,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    owner_id=player.id,
                    controller_id=player.id,
                    from_zone=was[0] if was is not None else None,
                    object_types=sorted(obj.type_words),
                    subtypes=sorted(obj.card.type_line.lower().partition("—")[2].split()),
                    colors=list(getattr(obj.card, "colors", None) or []),
                    is_token=bool(getattr(obj, "is_token", False)),
                ))

    def resync_graveyard_watch(self) -> None:
        """Re-baseline `announce_graveyard_arrivals` without firing (a direct board edit)."""
        self._zones_seen = self._zone_map()

    def hold_batches(self) -> None:
        """Keep the current batch open past this call (an interactive multi-pick)."""
        self._batch_hold = True

    def release_batches(self) -> None:
        """End a `hold_batches`: the picks made so far become one batch."""
        if getattr(self, "_batch_hold", False):
            self._batch_hold = False
            if getattr(self, "_batch_depth", 0) == 0:
                self._flush_batches()

    def _flush_batches(self) -> None:
        buffered, self._batch_buffer = list(getattr(self, "_batch_buffer", [])), []
        by_type: dict[str, list[GameEvent]] = {}
        for event in buffered:
            by_type.setdefault(event.type, []).append(event)
        for batch_of, members in by_type.items():
            self.fire_event(GameEvent(EventType.EVENT_BATCH, batch_of=batch_of, members=members))
        exits, self._graveyard_exits = list(getattr(self, "_graveyard_exits", [])), []
        if exits:
            self.fire_event(GameEvent(EventType.CARDS_LEFT_GRAVEYARD, cards=exits))

    def note_graveyard_exit(self, card: dict[str, Any]) -> None:
        """RULE 603.3f: a card left its owner's graveyard (``card`` is its snapshot).

        Cards that leave at once — one instruction, one SBA sweep, one interactive
        multi-pick — are one `CARDS_LEFT_GRAVEYARD` ("one or more cards leave your
        graveyard" triggers once), collected by the same `simultaneous` scope that
        batches the per-object events; outside every scope the card is its own event.
        """
        if getattr(self, "_batch_depth", 0) > 0 or getattr(self, "_batch_hold", False):
            if not hasattr(self, "_graveyard_exits"):
                self._graveyard_exits = []
            self._graveyard_exits.append(card)
        else:
            self.fire_event(GameEvent(EventType.CARDS_LEFT_GRAVEYARD, cards=[card]))

    def fire_event(self, event: GameEvent) -> GameEvent:
        """Record ``event`` and notify subscribers. Returns the event.

        This is deliberately consequence-free beyond notification —
        replacement effects are applied by the engine *before* it calls
        ``fire_event`` (the event here is what actually happened), and
        triggered abilities are queued by subscribers.
        """
        event.turn = self.internal_turn.number
        if event.type == EventType.ENTERS_BATTLEFIELD and "is_token" not in event.data:
            # The history reads whether a permanent was a token (Gyome), and the entering
            # object is on the battlefield right now; a copy of a card is a token too, so the
            # type line cannot answer it.
            entered = self.find_object(event.get("instance_id"))
            event.data["is_token"] = bool(entered is not None and entered.is_token)
        self.event_log.append(event)
        for subscriber in list(self._subscribers):
            subscriber(event)
        if event.type in self.BATCHED_EVENT_TYPES:
            if getattr(self, "_batch_depth", 0) > 0 or getattr(self, "_batch_hold", False):
                self._batch_buffer.append(event)
            else:
                self.fire_event(GameEvent(EventType.EVENT_BATCH, batch_of=event.type,
                                          members=[event]))
        return event

    def events_this_turn(self) -> "Iterator[GameEvent]":
        """Every event fired in the current turn, newest first (ENG-47).

        The log is chronological and every fired event is turn-stamped, so this stops
        at the first event of an earlier turn instead of scanning the whole game.
        """
        current = self.internal_turn.number
        for event in reversed(self.event_log):
            if event.turn != current:
                break
            yield event

    def events_last_turn(self) -> "Iterator[GameEvent]":
        """Events from the immediately preceding turn, newest first (RULE 500.1)."""
        previous = self.internal_turn.number - 1
        for event in reversed(self.event_log):
            if event.turn > previous:
                continue
            if event.turn < previous:
                break
            yield event

    def attacked_player_during_last_turn(self, attacker_id: str, defender_id: str) -> bool:
        """RULE 508.1/508.4: declarations in that player's latest own turn."""
        last_turn = next((event.turn for event in reversed(self.event_log)
                          if event.type == EventType.TURN_BEGIN and event.get("player_id") == attacker_id), None)
        if last_turn is None:
            return False
        return any(event.type == EventType.ATTACKS and event.turn == last_turn
                   and event.get("player_id") == attacker_id and event.get("declared")
                   and event.get("defender_kind") == "player"
                   and event.get("defending_player_id") == defender_id
                   for event in reversed(self.event_log))

    # -- Per-turn history, derived from the event log (ENG-47) -------------------
    # Each of these was a counter bumped at one site and reset in `GameEngine.begin_turn`;
    # it is now a fresh read over `events_this_turn()` (`turn_history`), so it can never
    # drift from what actually fired and needs no reset. The reset scope is the same for
    # everyone: this turn, for every player.

    @property
    def combats_this_turn(self) -> int:
        """Combat phases this turn so far (RULE 603.4's "first combat phase" intervening-if)."""
        return turn_history.combats(self.events_this_turn())

    @property
    def planar_die_rolls_this_turn(self) -> dict[str, int]:
        """How often each player rolled the planar die this turn (RULE 901.6b: the cost is {X})."""
        return turn_history.planar_die_rolls(self.events_this_turn())

    @property
    def life_gained_this_turn(self) -> dict[str, int]:
        """Life each player gained this turn (RULE 119.3)."""
        return turn_history.life_gained(self.events_this_turn())

    @property
    def life_lost_this_turn(self) -> dict[str, int]:
        """Life each player lost this turn — damage, life payments and "loses N life" alike."""
        return turn_history.life_lost(self.events_this_turn())

    @property
    def cards_discarded_this_turn(self) -> dict[str, int]:
        return turn_history.cards_discarded(self.events_this_turn())

    @property
    def cards_put_into_graveyard_from_hand_or_library_this_turn(self) -> dict[str, int]:
        """Cards each player put into their graveyard from hand or library this turn (Welcome the Dead)."""
        self.announce_graveyard_arrivals()  # the arrival events are detected lazily — flush before reading
        return turn_history.cards_put_into_graveyard_from_hand_or_library(self.events_this_turn())

    @property
    def cards_drawn_this_turn(self) -> dict[str, int]:
        """Cards each player drew this turn (RULE 121)."""
        return turn_history.cards_drawn(self.events_this_turn())

    @property
    def cards_drawn_this_turn_ids(self) -> dict[str, list[int]]:
        """The specific objects each player drew this turn, oldest first (Sylvan Library)."""
        return turn_history.cards_drawn_ids(self.events_this_turn())

    @property
    def spells_cast_this_turn(self) -> dict[str, int]:
        """Spells each player cast this turn (RULE 731.2; Damping Sphere)."""
        return turn_history.spells_cast(self.events_this_turn())

    @property
    def mana_spent_on_spells_this_turn(self) -> dict[str, int]:
        """Mana each player spent to cast spells this turn (RULE 700.14)."""
        return turn_history.mana_spent_on_spells(self.events_this_turn())

    @property
    def noncreature_spells_cast_this_turn(self) -> dict[str, int]:
        return turn_history.noncreature_spells_cast(self.events_this_turn())

    @property
    def cards_played_from_exile_this_turn(self) -> dict[str, int]:
        """Spells cast and lands played from exile by each player this turn (RULE 601.2a / 305.1)."""
        return turn_history.cards_played_from_exile(self.events_this_turn())

    @property
    def nonartifact_spells_cast_this_turn(self) -> dict[str, int]:
        return turn_history.nonartifact_spells_cast(self.events_this_turn())

    @property
    def cast_instant_or_sorcery_this_turn(self) -> dict[str, bool]:
        return turn_history.cast_instant_or_sorcery(self.events_this_turn())

    @property
    def greatest_instant_sorcery_mv_this_turn(self) -> dict[str, int]:
        return turn_history.greatest_instant_sorcery_mv(self.events_this_turn())

    @property
    def spell_colors_cast_this_turn(self) -> dict[str, set[str]]:
        return turn_history.spell_colors_cast(self.events_this_turn())

    @property
    def spell_color_cast_counts_this_turn(self) -> dict[str, dict[str, int]]:
        return turn_history.spell_color_cast_counts(self.events_this_turn())

    @property
    def spell_type_cast_counts_this_turn(self) -> dict[str, dict[str, int]]:
        return turn_history.spell_type_cast_counts(self.events_this_turn())

    @property
    def creature_type_spells_cast_this_turn(self) -> dict[str, set[str]]:
        return turn_history.creature_type_spells_cast(self.events_this_turn())

    @property
    def cast_x_spell_this_turn(self) -> set[str]:
        return turn_history.cast_x_spell(self.events_this_turn())

    @property
    def creatures_died_this_turn(self) -> dict[str, int]:
        """Creatures that died under each player's control this turn (RULE 700.4)."""
        return turn_history.creatures_died(self.events_this_turn())

    @property
    def nontoken_creatures_died_this_turn(self) -> dict[str, int]:
        """Nontoken creatures that died under each player's control this turn (RULE 700.4)."""
        return turn_history.nontoken_creatures_died(self.events_this_turn())

    @property
    def modified_creatures_died_this_turn(self) -> dict[str, int]:
        return turn_history.modified_creatures_died(self.events_this_turn())

    @property
    def combat_damage_to_players_this_turn(self) -> dict[int, set[str]]:
        """``{source instance id: players it dealt combat damage to}`` (RULE 120.3)."""
        return turn_history.combat_damage_to_players(self.events_this_turn())

    @property
    def noncombat_damage_to_opponents_this_turn(self) -> dict[str, int]:
        return turn_history.noncombat_damage_to_opponents(self.events_this_turn())

    @property
    def damage_dealt_to_players_this_turn(self) -> dict[str, int]:
        return turn_history.damage_dealt_to_players(self.events_this_turn())

    @property
    def damage_dealt_by_this_turn(self) -> dict[str, int]:
        return turn_history.damage_dealt_by(self.events_this_turn())

    @property
    def creatures_damaged_by_source_this_turn(self) -> dict[int, set[int]]:
        return turn_history.creatures_damaged_by_source(self.events_this_turn())

    @property
    def creature_card_to_graveyard_this_turn(self) -> set[str]:
        return turn_history.creature_card_to_graveyard(self.events_this_turn())

    @property
    def permanent_card_to_graveyard_this_turn(self) -> set[str]:
        return turn_history.permanent_card_to_graveyard(self.events_this_turn())

    @property
    def bends_this_turn(self) -> dict[str, set[str]]:
        return turn_history.bends(self.events_this_turn())

    @property
    def counter_placed_on_creature_this_turn(self) -> set[str]:
        return turn_history.counter_placed_on_creature(self.events_this_turn())

    @property
    def nontoken_creatures_entered_this_turn(self) -> dict[str, int]:
        return turn_history.nontoken_creatures_entered(self.events_this_turn())

    @property
    def lands_entered_this_turn(self) -> dict[str, int]:
        return turn_history.lands_entered(self.events_this_turn())

    @property
    def permanents_left_battlefield_this_turn(self) -> dict[str, int]:
        """Permanents that left the battlefield under each player's control (MEC-84)."""
        return turn_history.permanents_left_battlefield(self.events_this_turn())

    @property
    def creatures_left_battlefield_this_turn(self) -> dict[str, int]:
        return turn_history.creatures_left_battlefield(self.events_this_turn())

    @property
    def players_attacked_this_turn(self) -> set[str]:
        """Players who declared an attacker this turn (RULE 508.1a; Raid)."""
        return turn_history.players_attacked(self.events_this_turn())

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
            "clash_revealed": [
                obj.to_dict() for iid in self.clash_revealed
                if (obj := self.find_object(iid)) is not None
            ],
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

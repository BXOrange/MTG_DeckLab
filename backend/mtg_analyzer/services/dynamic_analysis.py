"""ANA-4: run N headless goldfish matches against a bot and report
turn-by-turn stats (mean + standard deviation across the matches).

Reference: docs/implementation-state/BACKLOG.md "ANA-4", `services/bots.py`,
`services/game_session.py`. The result is meant to sit alongside the
static, purely-arithmetic mana-curve estimate the "Deck analysieren" tab
already computes (`frontend/src/js/deckAnalysis.js`'s `simulateManaCurve`)
in a shared graph — this module is the actual-play half of that comparison.

Every match is a solo `GameSession` (`services/game_session.py`'s
`build_goldfish_engine`/`GameSession`, the same shape `POST /api/game/
goldfish` builds), driven end-to-end by one of `services/bots.py`'s `Bot`
subclasses. That combination is new: `Bot` has only ever driven a
*multiplayer* seat before, where `interactive_priority` is on and RULE 117
priority genuinely gets passed around. A goldfish session runs with that
flag off, and `GameEngine.pass_priority()` called with no player (`bots.py`'s
`_one_bot_action` fallback for "nothing to do") only ever resolves the top
of an already-non-empty stack — on an empty stack it's a no-op, so reusing
`run_bots`/`_one_bot_action` unchanged would spin forever on turn 1
(verified empirically while building this). The goldfish UI's own "Nächste
Entscheidung" button (`GameSession._apply_advance_to_decision`, action type
``advance_to_decision``) is what actually moves a solo game from one real
decision to the next, so `run_one_match` uses that as the "bot has nothing
to do" fallback instead.

Several of the requested metrics aren't tracked anywhere in the engine
today (only some of `GameState.stats` was ever meant for this). Rather than
touching the stats engine every real game pays for, this module computes
them itself from a match's own full (unredacted — there's no RULE 400.2
concern here, this is a solo simulation) state:

* **lands drawn** — not tracked by kind anywhere (`record_stat("draw", ...)`
  only counts total cards) — derived per turn as
  ``total lands in the shuffled library − lands still in the library``.
* **mana potential** — a live, on-demand computation
  (`game/mana_potential.py`), never persisted historically; sampled once
  per turn.
* **card advantage** — no existing definition (the concept normally
  compares two players' resources, and a goldfish has no opponent).
  Defined here as cumulative cards drawn so far minus (turn − 1) — RULE
  103.7a's "the starting player skips their first draw" baseline, so a
  perfectly ordinary game reads as 0 rather than sitting at a constant
  offset — documented as a simplification, the same way the static
  analysis tab already flags its own estimates as such.
* **tutors resolved** / **turn a commander entered the battlefield** — not
  tracked at all; both come from subscribing to the match's own event bus
  (`GameState.subscribe`) for `EventType.LIBRARY_SEARCHED` (fires for every
  library search, so this is "library searches", a superset of "tutors" in
  the strict sense — also counts fetch lands) and the first
  `EventType.ENTERS_BATTLEFIELD` of an ``is_commander`` object.

Mana *produced* per turn is already tracked (`GameSession.analysis()`'s
`mana_per_turn`) and is read back from there rather than re-derived.

A deck with a genuine infinite-mana combo would otherwise let `GreedyBot`
tap forever without the turn ever ending, wasting the whole per-match
action budget and reporting a nonsense "mana produced" figure for that
turn — `run_one_match` watches `GameState.mana_produced_this_turn` and
aborts the match once it crosses `INFINITE_MANA_THRESHOLD`, dropping that
one turn's snapshot (its `mana_produced` reading *is* the runaway number)
but keeping every earlier turn's real data in the aggregate. Counted
separately (`DynamicAnalysisResult.matches_aborted_infinite_mana`) rather
than silently folded into a lower `matches_run`, so the UI can say why —
alongside the mean/stddev turn the abort happened on
(`DynamicAnalysisResult.infinite_mana_turn`), since "the deck has an
infinite combo" is a lot more useful to a deckbuilder alongside "and it
usually comes online around turn N" than as a bare yes/no.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import queue
import random
import statistics
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from mtg_analyzer import config
from mtg_analyzer.game import mana_potential
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.services.bots import BOT_TYPES, Bot, create_bot
from mtg_analyzer.services.game_session import GOLDFISH, GameActionError, GameSession, build_goldfish_engine

logger = logging.getLogger(__name__)

#: Bounds enforced again by the API schema — kept here too as the ground
#: truth so a direct (test) caller can't request something that would run
#: for an unreasonable amount of wall-clock time.
MAX_NUM_MATCHES = 200
MAX_MAX_TURNS = 30

#: A hard per-match action-count safety valve, the same idea as
#: `services/bots.py`'s `MAX_BOT_ACTIONS` — sized generously per turn (a
#: real turn is a handful of `advance_to_decision` fast-forwards plus
#: whatever the bot actually plays) so a buggy effect loop can't hang a job.
_ACTIONS_PER_TURN_BUDGET = 80

#: A deck with a genuine infinite-mana combo (an untap effect feeding a
#: mana ability, or similar) lets `GreedyBot` tap forever without the turn
#: ever ending — that would otherwise just eat the whole `action_budget`
#: doing nothing useful, and the "mana produced" reading for that match
#: would be nonsense (dwarfing every other match's, skewing the mean far
#: past what the deck actually does turn to turn). No real deck produces
#: anywhere near this much mana in one turn without looping, so crossing it
#: is treated as "this match hit an infinite loop", not "a huge turn" —
#: `run_one_match` aborts that match right there instead of grinding on.
INFINITE_MANA_THRESHOLD = 1000

#: The dummy "Goldfisch" opponent's life total for this module's matches
#: specifically (`build_goldfish_engine`'s ``dummy_starting_life``) — much
#: higher than a real game's 40, so combat damage essentially never ends a
#: match early. This harness reports turn-by-turn mana/land development,
#: not who wins; a `GreedyBot` attacking every turn otherwise kills a real
#: 40-life dummy within a handful of turns for any reasonably aggressive
#: deck, which truncates that match's per-turn samples right there. Averaged
#: across many matches, that's not just fewer samples — it's a
#: survivorship-bias artifact: the matches still contributing to a later
#: turn's mean are disproportionately the ones that developed *slower*,
#: which drags metrics like "lands drawn" down turn over turn even though
#: every individual match's own count only ever goes up. High enough that
#: no real deck deals this much damage within `MAX_MAX_TURNS`, without
#: being unbounded (a genuine infinite-damage combo still hits
#: `INFINITE_MANA_THRESHOLD` or the action budget first).
DUMMY_ANALYSIS_LIFE = 100_000

#: Per-turn metrics this module samples/derives. Kept as one tuple so the
#: match loop, the aggregator, and the job result shape can't drift apart.
PER_TURN_METRICS = ("mana_potential", "lands_drawn", "cards_drawn", "card_advantage", "mana_produced")

#: Below this many matches, `run_dynamic_analysis` runs them in-process
#: even when `config.DYNAMIC_ANALYSIS_MATCH_WORKERS` would allow a pool: a
#: `ProcessPoolExecutor` worker spawns a fresh interpreter that re-imports
#: the whole engine (~1s each on a `spawn` platform like macOS), which
#: isn't worth paying to parallelise only a handful of short simulations.
_MIN_MATCHES_FOR_PROCESS_POOL = 4


@dataclass
class MatchResult:
    """One simulated goldfish game's raw (unaggregated) numbers."""

    turns_reached: int
    per_turn: dict[int, dict[str, float]]
    tutors_resolved: int
    commander_turns: dict[str, int]
    #: Whether this match was cut short by `INFINITE_MANA_THRESHOLD` — the
    #: `per_turn`/`tutors_resolved`/`commander_turns` collected up to that
    #: point are still real data and stay in the aggregate; only the turns
    #: past the abort are missing (fewer samples for those, same as a match
    #: that reached `game_over` early).
    aborted_infinite_mana: bool = False
    #: The turn `aborted_infinite_mana` happened on — `None` unless it did.
    #: Aggregated across matches into `DynamicAnalysisResult.
    #: infinite_mana_turn` so a deck with a real combo reads as "goes
    #: infinite around turn N" rather than just "some matches were cut
    #: short".
    aborted_turn: Optional[int] = None
    #: Per favorite card name: {"drawn_turn"/"cast_turn"/"castable_turn":
    #: <turn or None>}. Empty when `run_one_match` wasn't given any
    #: favorite card names.
    favorite_cards: dict[str, dict[str, Optional[int]]] = field(default_factory=dict)


def run_one_match(
    library: list[Card],
    commanders: Optional[list[Card]],
    *,
    bot: Bot,
    starting_life: int = 40,
    starting_hand: int = 7,
    game_format: Optional[str] = None,
    max_turns: int = 10,
    favorite_card_names: Optional[set[str]] = None,
) -> MatchResult:
    """Play one solo goldfish game to completion (or `max_turns`), with
    `bot` driving the only real seat (id ``"p1"`` — `build_goldfish_engine`
    always assigns that id, so `bot.player_id` must be it too).

    ``library`` is used as given (already shuffled by the caller — see
    `run_dynamic_analysis`, which reshuffles a fresh copy per match) so this
    function stays deterministic given a deterministic input, matching
    every other builder in `services/game_session.py`.
    """
    engine = build_goldfish_engine(
        library,
        commanders,
        starting_life=starting_life,
        starting_hand=starting_hand,
        with_dummy=True,
        game_format=game_format,
        dummy_starting_life=DUMMY_ANALYSIS_LIFE,
    )
    session = GameSession(engine, mode=GOLDFISH, starting_hand=starting_hand, require_setup=True)
    state = engine.state
    player = state.player_by_id("p1")

    total_lands = sum(1 for c in library if c.is_land)
    commander_names = {c.name for c in (commanders or [])}
    favorite_names = favorite_card_names or set()

    tutors_resolved = 0
    commander_turns: dict[str, int] = {}
    #: Per favorite card: first turn seen in the sampled hand / first turn
    #: actually cast / first turn a legal (unlocked) cast action for it
    #: existed while in hand — `None` until that happens, see
    #: `MatchResult.favorite_cards`.
    favorite_drawn_turn: dict[str, Optional[int]] = {name: None for name in favorite_names}
    favorite_cast_turn: dict[str, Optional[int]] = {name: None for name in favorite_names}
    favorite_castable_turn: dict[str, Optional[int]] = {name: None for name in favorite_names}

    def on_event(event: GameEvent) -> None:
        nonlocal tutors_resolved
        if event.type == EventType.LIBRARY_SEARCHED:
            tutors_resolved += 1
        elif event.type == EventType.ENTERS_BATTLEFIELD:
            obj = state.find_object(event.get("instance_id"))
            if obj is None or not getattr(obj, "is_commander", False):
                return
            name = getattr(obj, "name", None)
            if name in commander_names and name not in commander_turns:
                commander_turns[name] = state.turn_number
        elif event.type == EventType.SPELL_CAST:
            name = event.get("spell")
            # A countered spell was still cast (RULE 601.2i) — SPELL_CAST
            # fires at cast time, before resolution, which is exactly the
            # "was it played" semantics wanted here, not "did it resolve".
            if name in favorite_names and favorite_cast_turn.get(name) is None:
                favorite_cast_turn[name] = state.turn_number

    state.subscribe(on_event)

    per_turn: dict[int, dict[str, float]] = {}
    sampled_turns: set[int] = set()

    def maybe_sample() -> None:
        # One snapshot per turn, taken the first time that turn reaches its
        # second main phase — `GameSession._step_has_interaction` always
        # stops "Nächste Entscheidung" there, so every turn that starts at
        # all reaches this point, and by then that turn's land drop/casts
        # have already happened.
        turn = state.turn_number
        if turn < 1 or turn in sampled_turns or state.current_step != "main2":
            return
        sampled_turns.add(turn)
        lands_remaining = sum(1 for o in player.library if o.is_land)
        cards_drawn = sum(
            rec["amount"]
            for rec in state.stats["timeline"]
            if rec["player_id"] == "p1" and rec["kind"] == "draw" and rec["turn"] <= turn
        )
        # RULE 103.7a: the starting player skips their very first draw, so a
        # perfectly ordinary solo game has drawn (turn - 1) cards by turn N,
        # not `turn` — using that as the baseline means 0 reads as "exactly
        # on curve" rather than every normal game sitting at a constant -1.
        per_turn[turn] = {
            "mana_potential": float(mana_potential.max_potential_total(engine, player)),
            "lands_drawn": float(total_lands - lands_remaining),
            "cards_drawn": float(cards_drawn),
            "card_advantage": float(cards_drawn - max(0, turn - 1)),
        }

    aborted_infinite_mana = False
    actions_used = 0
    action_budget = max(200, max_turns * _ACTIONS_PER_TURN_BUDGET)
    while actions_used < action_budget:
        if state.game_over or state.turn_number > max_turns:
            break
        actions = session.legal_actions()
        if not actions:
            break
        if favorite_names:
            # Checked every iteration, not just once per turn like
            # `maybe_sample()` — a `GreedyBot` can draw-then-cast a favorite
            # card within the very same turn, before that turn's single
            # main2 snapshot would ever see it still in hand.
            hand_names = {o.name for o in player.hand}
            for name in favorite_names:
                if name in hand_names and favorite_drawn_turn.get(name) is None:
                    favorite_drawn_turn[name] = state.turn_number
            # Reuses the engine's own affordability/legality check (an
            # offered, unlocked cast_spell action already means "this can be
            # paid and cast right now") rather than recomputing mana
            # potential against the card's cost separately.
            for action in actions:
                if action.get("type") != "cast_spell" or action.get("locked"):
                    continue
                name = action.get("name")
                if name in favorite_names and favorite_castable_turn.get(name) is None:
                    favorite_castable_turn[name] = state.turn_number
        view = session.view()
        action = bot.decide(view, actions)
        if action is None:
            action = {"type": "advance_to_decision"}
        try:
            session.apply_action(action)
        except GameActionError:
            # Mirrors `run_bots`'s "one bad offer shouldn't wedge the whole
            # run": note the failure so the bot doesn't retry the exact same
            # offer, then just fast-forward past it.
            if action.get("type") == "advance_to_decision":
                break
            bot.note_failure(action)
            try:
                session.apply_action({"type": "advance_to_decision"})
            except GameActionError:
                break
        actions_used += 1
        maybe_sample()
        # `mana_produced_this_turn` resets every `begin_turn` (models/
        # game_state.py), so this sum is genuinely "this turn's" production
        # — a real turn's worth, not a running total that would eventually
        # cross the threshold in any long game.
        if sum(state.mana_produced_this_turn.get("p1", {}).values()) > INFINITE_MANA_THRESHOLD:
            aborted_infinite_mana = True
            break

    aborted_turn: Optional[int] = None
    if aborted_infinite_mana:
        # The turn the loop was caught on has a `mana_produced` reading
        # that's exactly the runaway number that triggered the abort — drop
        # its whole snapshot rather than let that one turn's aggregate mean
        # get dragged along with it. Every earlier turn's data is unaffected
        # (sampled before the loop started) and stays in.
        aborted_turn = state.turn_number
        per_turn.pop(state.turn_number, None)

    # Mana actually produced is already tracked per turn — read it back
    # rather than re-deriving it from the timeline ourselves.
    mana_per_turn = session.analysis()["players"]["p1"]["mana_per_turn"]
    for turn, snapshot in per_turn.items():
        snapshot["mana_produced"] = float(mana_per_turn.get(turn, 0))

    favorite_result = {
        name: {
            "drawn_turn": favorite_drawn_turn[name],
            "cast_turn": favorite_cast_turn[name],
            "castable_turn": favorite_castable_turn[name],
        }
        for name in favorite_names
    }

    return MatchResult(
        turns_reached=min(state.turn_number, max_turns),
        per_turn=per_turn,
        tutors_resolved=tutors_resolved,
        commander_turns=commander_turns,
        aborted_infinite_mana=aborted_infinite_mana,
        aborted_turn=aborted_turn,
        favorite_cards=favorite_result,
    )


def _mean_stddev(values: list[float]) -> dict[str, float]:
    """Population mean/stddev (every simulated match is used, not a sample
    of a larger population) — stddev is 0 for fewer than 2 values rather
    than raising `statistics.StatisticsError`."""
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "n": 0}
    return {
        "mean": statistics.mean(values),
        "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "n": len(values),
    }


@dataclass
class FavoriteCardStats:
    """Aggregated across every match that ran (`matches_run`), not just the
    ones where the card actually showed up — a fraction, not a mean over a
    filtered subset, so "never drawn in 20/20 matches" reads as 0.0 rather
    than being silently absent."""

    drawn_fraction: float
    cast_fraction: float
    #: mean/stddev/n turn among only the matches where it *was* cast
    #: (`_mean_stddev` shape) — turn-of-play is meaningless to average over
    #: matches where it never happened.
    cast_turn: dict[str, float]
    #: Fraction of matches where a legal, unlocked cast action for this
    #: card existed at some point while it was in hand, but it was never
    #: actually cast that match. See `run_one_match`'s docstring on the
    #: `GoldfishBot` caveat — this number is only meaningful with a bot that
    #: actually casts spells.
    castable_but_never_cast_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawnFraction": self.drawn_fraction,
            "castFraction": self.cast_fraction,
            "castTurn": self.cast_turn,
            "castableButNeverCastFraction": self.castable_but_never_cast_fraction,
        }


@dataclass
class DynamicAnalysisResult:
    matches_requested: int
    matches_run: int
    max_turns: int
    bot_kind: str
    per_turn: list[dict[str, Any]]
    tutors_resolved: dict[str, float]
    commander_turns: dict[str, dict[str, float]]
    #: How many of `matches_run` were cut short by `INFINITE_MANA_
    #: THRESHOLD` (still counted in `matches_run` and contribute whatever
    #: turns they reached before the abort — see `MatchResult.
    #: aborted_infinite_mana`) — surfaced separately so the UI can flag it
    #: rather than a deck with a real combo silently reading as "normal".
    matches_aborted_infinite_mana: int = 0
    #: Mean/stddev/n (see `_mean_stddev`) of the turn `matches_aborted_
    #: infinite_mana` matches were cut short on — i.e. roughly how many
    #: turns the deck needs to reliably assemble its infinite-mana combo.
    #: `n` is 0 (mean/stddev 0.0) whenever no match aborted, distinct from
    #: a combo that always goes off turn 1.
    infinite_mana_turn: dict[str, float] = field(default_factory=lambda: {"mean": 0.0, "stddev": 0.0, "n": 0})
    #: Keyed by card name — see `FavoriteCardStats`. Empty unless the
    #: caller passed favorite card names in.
    favorite_cards: dict[str, FavoriteCardStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchesRequested": self.matches_requested,
            "matchesRun": self.matches_run,
            "maxTurns": self.max_turns,
            "botKind": self.bot_kind,
            "perTurn": self.per_turn,
            "tutorsResolved": self.tutors_resolved,
            "commanderTurns": self.commander_turns,
            "matchesAbortedInfiniteMana": self.matches_aborted_infinite_mana,
            "infiniteManaTurn": self.infinite_mana_turn,
            "favoriteCards": {name: stats.to_dict() for name, stats in self.favorite_cards.items()},
        }


class _ProcessPoolUnavailable(RuntimeError):
    """Raised inside `run_dynamic_analysis` when a `ProcessPoolExecutor`
    can't be created or every worker died before doing any work — the
    caller then re-runs the whole batch in-process."""


def _match_worker_count(num_matches: int) -> int:
    """How many worker processes to fan this job's matches across.

    Reads `config.DYNAMIC_ANALYSIS_MATCH_WORKERS` (0 = one per CPU core),
    then clamps: never more workers than matches, and a return of ``1``
    means "run in-process, no pool" — which is also what a small job
    (`_MIN_MATCHES_FOR_PROCESS_POOL`) always gets, spawn cost not being
    worth it there.
    """
    configured = config.DYNAMIC_ANALYSIS_MATCH_WORKERS
    if configured == 0:
        configured = os.cpu_count() or 1
    if configured <= 1 or num_matches < _MIN_MATCHES_FOR_PROCESS_POOL:
        return 1
    return max(1, min(configured, num_matches))


def _run_one_match_worker(payload: dict[str, Any]) -> MatchResult:
    """`ProcessPoolExecutor` entrypoint: rebuild the bot in this process
    and play one match.

    Only picklable data crosses the process boundary — a pre-shuffled
    `list[Card]` plus primitives in, a `MatchResult` of plain
    dicts/ints/bools out. The `GameSession`/`GameEngine` a match builds
    never leaves the worker. Kept module-level so it's picklable by
    reference.
    """
    bot = create_bot(payload["bot_kind"], "p1")
    return run_one_match(
        payload["library"],
        payload["commanders"],
        bot=bot,
        starting_life=payload["starting_life"],
        starting_hand=payload["starting_hand"],
        game_format=payload["game_format"],
        max_turns=payload["max_turns"],
        favorite_card_names=payload["favorite_card_names"],
    )


def _run_matches_pooled(
    shuffled_libraries: list[list[Card]],
    payload_base: dict[str, Any],
    worker_count: int,
    on_progress: Optional[Callable[[int, int], None]],
    total: int,
) -> list[Optional[MatchResult]]:
    """Play every pre-shuffled library in a `ProcessPoolExecutor`, one
    submission per match, returning results in completion order (a match
    that raised in its worker contributes ``None``, same skip-don't-abort
    rule as the in-process path).

    Raises `_ProcessPoolUnavailable` if the pool can't be constructed at
    all, so the caller can fall back to running the batch in-process.
    """
    try:
        executor = concurrent.futures.ProcessPoolExecutor(max_workers=worker_count)
    except (OSError, ValueError) as exc:  # pragma: no cover - platform/rlimit dependent
        raise _ProcessPoolUnavailable(str(exc)) from exc

    results: list[Optional[MatchResult]] = []
    completed = 0
    with executor:
        futures = [
            executor.submit(_run_one_match_worker, {**payload_base, "library": library})
            for library in shuffled_libraries
        ]
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            try:
                results.append(future.result())
            except concurrent.futures.BrokenProcessPool:
                logger.exception("dynamic analysis: a worker process died, skipping its match")
                results.append(None)
            except Exception:  # pragma: no cover - defensive, see run_one_match
                logger.exception("dynamic analysis: a match raised in a worker process, skipping")
                results.append(None)
            if on_progress:
                on_progress(completed, total)
    return results


def run_dynamic_analysis(
    library: list[Card],
    commanders: Optional[list[Card]],
    *,
    bot_kind: str,
    num_matches: int,
    max_turns: int,
    starting_life: int = 40,
    starting_hand: int = 7,
    game_format: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    favorite_card_names: Optional[set[str]] = None,
) -> DynamicAnalysisResult:
    """Run `num_matches` independent `run_one_match` calls (a fresh library
    shuffle each time) and aggregate every metric into mean/stddev.

    The matches are independent and CPU-bound, so when
    `config.DYNAMIC_ANALYSIS_MATCH_WORKERS` allows it (and the job is big
    enough to be worth the spawn cost — `_match_worker_count`) they run in
    parallel across a `ProcessPoolExecutor`, which is real GIL-bypassing
    speed-up. Otherwise they run one after another in this process. Either
    way the shuffles happen here, up front, off the process-global RNG, so
    a given RNG state produces the same set of matches regardless of how
    they're scheduled.

    ``on_progress(completed, total)`` is called after every match (including
    a failed one) — the job-manager below uses it to drive a progress bar.
    A single match raising is logged and skipped rather than losing the
    whole batch, mirroring `services/bots.py`'s `run_bots` "one bad action
    doesn't wedge the table" philosophy.
    """
    num_matches = max(1, min(MAX_NUM_MATCHES, int(num_matches)))
    max_turns = max(1, min(MAX_MAX_TURNS, int(max_turns)))
    if bot_kind not in BOT_TYPES:
        raise ValueError(f"unknown bot kind {bot_kind!r}")

    per_turn_values: dict[int, dict[str, list[float]]] = {
        turn: {metric: [] for metric in PER_TURN_METRICS} for turn in range(1, max_turns + 1)
    }
    tutor_values: list[float] = []
    commander_turn_values: dict[str, list[float]] = {}
    favorite_names = favorite_card_names or set()
    favorite_drawn_count: dict[str, int] = {name: 0 for name in favorite_names}
    favorite_cast_count: dict[str, int] = {name: 0 for name in favorite_names}
    favorite_cast_turn_values: dict[str, list[float]] = {name: [] for name in favorite_names}
    favorite_castable_never_cast_count: dict[str, int] = {name: 0 for name in favorite_names}

    matches_run = 0
    matches_aborted_infinite_mana = 0
    infinite_mana_turn_values: list[float] = []

    def ingest(result: MatchResult) -> None:
        """Fold one finished match's numbers into the running aggregates.
        Order-independent (every step is an append or a counter bump), so
        it's safe to feed matches back in whatever order they complete."""
        nonlocal matches_run, matches_aborted_infinite_mana
        matches_run += 1
        if result.aborted_infinite_mana:
            matches_aborted_infinite_mana += 1
            if result.aborted_turn is not None:
                infinite_mana_turn_values.append(float(result.aborted_turn))
        for turn, snapshot in result.per_turn.items():
            bucket = per_turn_values.get(turn)
            if bucket is None:
                continue
            for metric in PER_TURN_METRICS:
                bucket[metric].append(snapshot.get(metric, 0.0))
        tutor_values.append(float(result.tutors_resolved))
        for name, turn in result.commander_turns.items():
            commander_turn_values.setdefault(name, []).append(float(turn))
        for name, card_result in result.favorite_cards.items():
            if card_result["drawn_turn"] is not None:
                favorite_drawn_count[name] += 1
            if card_result["cast_turn"] is not None:
                favorite_cast_count[name] += 1
                favorite_cast_turn_values[name].append(float(card_result["cast_turn"]))
            elif card_result["castable_turn"] is not None:
                favorite_castable_never_cast_count[name] += 1

    # Shuffle every match's library up front, off the process-global RNG,
    # so the set of games played is fixed before any scheduling decision —
    # a pooled run and an in-process run see the same inputs.
    shuffled_libraries: list[list[Card]] = []
    for _ in range(num_matches):
        shuffled = list(library)
        random.shuffle(shuffled)
        shuffled_libraries.append(shuffled)
    payload_base: dict[str, Any] = {
        "bot_kind": bot_kind,
        "commanders": commanders,
        "starting_life": starting_life,
        "starting_hand": starting_hand,
        "game_format": game_format,
        "max_turns": max_turns,
        "favorite_card_names": favorite_names,
    }

    worker_count = _match_worker_count(num_matches)
    pooled_results: Optional[list[Optional[MatchResult]]] = None
    if worker_count > 1:
        try:
            pooled_results = _run_matches_pooled(
                shuffled_libraries, payload_base, worker_count, on_progress, num_matches
            )
        except _ProcessPoolUnavailable as exc:
            logger.warning(
                "dynamic analysis: process pool unavailable (%s); running matches in-process", exc
            )
            pooled_results = None

    if pooled_results is not None:
        for result in pooled_results:
            if result is not None:
                ingest(result)
        if matches_run == 0 and num_matches > 0:
            # Every worker failed before doing anything useful — treat the
            # pool as unusable rather than reporting an empty analysis, and
            # replay the same shuffled libraries in-process below.
            logger.warning("dynamic analysis: no match completed under the process pool; retrying in-process")
            pooled_results = None

    if pooled_results is None:
        for i, shuffled in enumerate(shuffled_libraries):
            bot = create_bot(bot_kind, "p1")
            try:
                result = run_one_match(
                    shuffled,
                    commanders,
                    bot=bot,
                    starting_life=starting_life,
                    starting_hand=starting_hand,
                    game_format=game_format,
                    max_turns=max_turns,
                    favorite_card_names=favorite_names,
                )
            except Exception:  # pragma: no cover - defensive, see docstring
                logger.exception("dynamic analysis: match %d/%d failed, skipping", i + 1, num_matches)
                if on_progress:
                    on_progress(i + 1, num_matches)
                continue
            ingest(result)
            if on_progress:
                on_progress(i + 1, num_matches)

    per_turn = [
        {"turn": turn, **{metric: _mean_stddev(values[metric]) for metric in PER_TURN_METRICS}}
        for turn, values in sorted(per_turn_values.items())
    ]
    commander_turns = {
        name: _mean_stddev(turns) for name, turns in commander_turn_values.items()
    }
    # Fraction denominators are matches_run, not num_matches — a match that
    # raised and was skipped never contributed a favorite_cards entry
    # either, same as every other metric above.
    denominator = max(1, matches_run)
    favorite_cards = {
        name: FavoriteCardStats(
            drawn_fraction=favorite_drawn_count[name] / denominator,
            cast_fraction=favorite_cast_count[name] / denominator,
            cast_turn=_mean_stddev(favorite_cast_turn_values[name]),
            castable_but_never_cast_fraction=favorite_castable_never_cast_count[name] / denominator,
        )
        for name in favorite_names
    }

    return DynamicAnalysisResult(
        matches_requested=num_matches,
        matches_run=matches_run,
        max_turns=max_turns,
        bot_kind=bot_kind,
        per_turn=per_turn,
        tutors_resolved=_mean_stddev(tutor_values),
        commander_turns=commander_turns,
        matches_aborted_infinite_mana=matches_aborted_infinite_mana,
        infinite_mana_turn=_mean_stddev(infinite_mana_turn_values),
        favorite_cards=favorite_cards,
    )


# -- Background job registry --------------------------------------------


@dataclass
class DynamicAnalysisJob:
    id: str
    status: str = "queued"  # "queued" | "running" | "done" | "error"
    total: int = 0
    completed: int = 0
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "result": self.result,
            "error": self.error,
        }


class _JobWorkerPool:
    """A fixed-size pool of daemon threads pulling job callables off a FIFO
    `queue.Queue`, sized by `config.DYNAMIC_ANALYSIS_WORKERS`.

    Replaces the previous "one `threading.Thread` per job" approach: that
    let concurrent dynamic-analysis requests spawn an unbounded number of OS
    threads, all CPU-bound and all fighting the GIL (and the rest of the
    process, including ordinary request handling) at once — the more
    requests piled up, the worse *every* one of them got, with no cap.
    Here, at most `num_workers` jobs ever run at the same time; anything
    past that just waits in the queue as a `"queued"` job (see
    `DynamicAnalysisJob.status`) until a worker frees up. Workers are
    daemon threads that block on `queue.get()` forever — same lifetime
    convention as every other background thread in this module, so the
    process still exits cleanly without an explicit shutdown hook.

    This pool is an **admission cap**, not the thing that makes an analysis
    fast: each job's own matches are what get parallelised for speed, over
    a `ProcessPoolExecutor` inside `run_dynamic_analysis`
    (`config.DYNAMIC_ANALYSIS_MATCH_WORKERS`). Keeping the job count capped
    here stops N concurrent jobs from launching N process pools that
    together oversubscribe the machine.
    """

    def __init__(self, num_workers: int) -> None:
        self.num_workers = num_workers
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        for i in range(num_workers):
            threading.Thread(target=self._worker_loop, name=f"dynamic-analysis-worker-{i}", daemon=True).start()

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                task()
            except Exception:  # pragma: no cover - defensive, a task itself already catches
                logger.exception("dynamic analysis worker: task raised")
            finally:
                self._queue.task_done()

    def submit(self, task: Callable[[], None]) -> None:
        self._queue.put(task)


class DynamicAnalysisJobs:
    """In-memory registry of queued/running/finished simulation jobs (ANA-4),
    backed by a shared `_JobWorkerPool` so a burst of requests can't
    overload the server (see that class's docstring).

    Jobs live in a small FIFO-capped dict — no persistence, no
    cross-restart resumption, the same as every other in-memory service
    here (`GameSessionManager._sessions`, `Lobby`'s tables).
    """

    _MAX_JOBS = 20

    def __init__(self, num_workers: Optional[int] = None) -> None:
        self._jobs: "OrderedDict[str, DynamicAnalysisJob]" = OrderedDict()
        self._lock = threading.Lock()
        self._pool = _JobWorkerPool(num_workers if num_workers is not None else config.DYNAMIC_ANALYSIS_WORKERS)

    def start(
        self,
        library: list[Card],
        commanders: Optional[list[Card]],
        *,
        bot_kind: str,
        num_matches: int,
        max_turns: int,
        starting_life: int = 40,
        starting_hand: int = 7,
        game_format: Optional[str] = None,
        favorite_card_names: Optional[set[str]] = None,
    ) -> str:
        total = max(1, min(MAX_NUM_MATCHES, int(num_matches)))
        job = DynamicAnalysisJob(id=str(uuid.uuid4()), total=total)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > self._MAX_JOBS:
                self._jobs.popitem(last=False)

        def on_progress(completed: int, _total: int) -> None:
            job.completed = completed

        def run() -> None:
            job.status = "running"
            try:
                result = run_dynamic_analysis(
                    library,
                    commanders,
                    bot_kind=bot_kind,
                    num_matches=num_matches,
                    max_turns=max_turns,
                    starting_life=starting_life,
                    starting_hand=starting_hand,
                    game_format=game_format,
                    on_progress=on_progress,
                    favorite_card_names=favorite_card_names,
                )
                job.result = result.to_dict()
                job.status = "done"
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("dynamic analysis job %s failed", job.id)
                job.error = str(exc)
                job.status = "error"

        self._pool.submit(run)
        return job.id

    def get(self, job_id: str) -> Optional[DynamicAnalysisJob]:
        with self._lock:
            return self._jobs.get(job_id)

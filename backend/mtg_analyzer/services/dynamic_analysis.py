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
than silently folded into a lower `matches_run`, so the UI can say why.
"""

from __future__ import annotations

import logging
import random
import statistics
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

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

#: Per-turn metrics this module samples/derives. Kept as one tuple so the
#: match loop, the aggregator, and the job result shape can't drift apart.
PER_TURN_METRICS = ("mana_potential", "lands_drawn", "cards_drawn", "card_advantage", "mana_produced")


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


def run_one_match(
    library: list[Card],
    commanders: Optional[list[Card]],
    *,
    bot: Bot,
    starting_life: int = 40,
    starting_hand: int = 7,
    game_format: Optional[str] = None,
    max_turns: int = 10,
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
    )
    session = GameSession(engine, mode=GOLDFISH, starting_hand=starting_hand, require_setup=True)
    state = engine.state
    player = state.player_by_id("p1")

    total_lands = sum(1 for c in library if c.is_land)
    commander_names = {c.name for c in (commanders or [])}

    tutors_resolved = 0
    commander_turns: dict[str, int] = {}

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

    if aborted_infinite_mana:
        # The turn the loop was caught on has a `mana_produced` reading
        # that's exactly the runaway number that triggered the abort — drop
        # its whole snapshot rather than let that one turn's aggregate mean
        # get dragged along with it. Every earlier turn's data is unaffected
        # (sampled before the loop started) and stays in.
        per_turn.pop(state.turn_number, None)

    # Mana actually produced is already tracked per turn — read it back
    # rather than re-deriving it from the timeline ourselves.
    mana_per_turn = session.analysis()["players"]["p1"]["mana_per_turn"]
    for turn, snapshot in per_turn.items():
        snapshot["mana_produced"] = float(mana_per_turn.get(turn, 0))

    return MatchResult(
        turns_reached=min(state.turn_number, max_turns),
        per_turn=per_turn,
        tutors_resolved=tutors_resolved,
        commander_turns=commander_turns,
        aborted_infinite_mana=aborted_infinite_mana,
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
        }


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
) -> DynamicAnalysisResult:
    """Run `num_matches` independent `run_one_match` calls (a fresh library
    shuffle each time) and aggregate every metric into mean/stddev.

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

    matches_run = 0
    matches_aborted_infinite_mana = 0
    for i in range(num_matches):
        shuffled = list(library)
        random.shuffle(shuffled)
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
            )
        except Exception:  # pragma: no cover - defensive, see docstring
            logger.exception("dynamic analysis: match %d/%d failed, skipping", i + 1, num_matches)
            if on_progress:
                on_progress(i + 1, num_matches)
            continue

        matches_run += 1
        if result.aborted_infinite_mana:
            matches_aborted_infinite_mana += 1
        for turn, snapshot in result.per_turn.items():
            bucket = per_turn_values.get(turn)
            if bucket is None:
                continue
            for metric in PER_TURN_METRICS:
                bucket[metric].append(snapshot.get(metric, 0.0))
        tutor_values.append(float(result.tutors_resolved))
        for name, turn in result.commander_turns.items():
            commander_turn_values.setdefault(name, []).append(float(turn))
        if on_progress:
            on_progress(i + 1, num_matches)

    per_turn = [
        {"turn": turn, **{metric: _mean_stddev(values[metric]) for metric in PER_TURN_METRICS}}
        for turn, values in sorted(per_turn_values.items())
    ]
    commander_turns = {
        name: _mean_stddev(turns) for name, turns in commander_turn_values.items()
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
    )


# -- Background job registry --------------------------------------------


@dataclass
class DynamicAnalysisJob:
    id: str
    status: str = "running"  # "running" | "done" | "error"
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


class DynamicAnalysisJobs:
    """In-memory registry of running/finished simulation jobs (ANA-4).

    The ticket asks for this to run "in the background". There's no
    existing async-job pattern in this codebase to plug into (checked —
    only the `GameSessionManager`/`Lobby` in-memory singletons), so this is
    new: one `threading.Thread` per job. The engine is synchronous
    CPU-bound Python and this is a single-process, local-dev-scale app, so a
    thread is simpler than wiring an executor for what amounts to the same
    thing. Jobs live in a small FIFO-capped dict — no persistence, no
    cross-restart resumption, the same as every other in-memory service
    here (`GameSessionManager._sessions`, `Lobby`'s tables).
    """

    _MAX_JOBS = 20

    def __init__(self) -> None:
        self._jobs: "OrderedDict[str, DynamicAnalysisJob]" = OrderedDict()
        self._lock = threading.Lock()

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
                )
                job.result = result.to_dict()
                job.status = "done"
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("dynamic analysis job %s failed", job.id)
                job.error = str(exc)
                job.status = "error"

        threading.Thread(target=run, name=f"dynamic-analysis-{job.id}", daemon=True).start()
        return job.id

    def get(self, job_id: str) -> Optional[DynamicAnalysisJob]:
        with self._lock:
            return self._jobs.get(job_id)

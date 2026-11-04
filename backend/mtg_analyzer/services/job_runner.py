"""ANA-6: a bounded, fair, in-memory job queue with a worker-thread runner.

Built for the dynamic analysis (`services/dynamic_analysis.py`) and shaped so
ANA-5's durable missing-card discovery job can reuse it. Two layers:

* `JobStore` owns *state*: every known job, the pending jobs grouped per owner
  (round-robin dispatch), per-owner running counts and the per-owner finished
  results (retention + TTL). It is plain in-memory data behind a handful of
  methods and no locking of its own: the runner calls it under its lock.
* `JobRunner` owns *policy and execution*: admission (bounded queue, per-owner
  pending limit, explicit refusal instead of eviction), worker threads that
  take the next fair job, cancellation, retention enforcement, the TTL sweep
  and shutdown.

ANA-5 extension points (nothing durable is built here):

* Persistence: subclass/replace `JobStore` with a SQLite-backed one under
  `MTG_DATA_DIR`; the runner only talks to the store's methods. A durable job
  needs a payload instead of the in-memory `Job.run` closure, so `submit`
  would take ``(kind, payload)`` and resolve the callable through a
  ``kind -> handler`` registry on restart (re-queue ``queued``/``running`` rows).
* Retry: `_execute` is the single place a failed run is classified; a retry
  policy (attempt counter + backoff, re-`enqueue`) belongs there.
* Coalescing: `submit` is the single admission point; look up an existing
  pending job by a ``(kind, key)`` there and return it instead of enqueuing.
* Fairness unit: the `owner` string. A system-owned job (ANA-5) can use its own
  owner key and so competes as one more participant in the round-robin.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: Job states, as returned by the poll.
STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
FINISHED_STATES = frozenset({STATE_DONE, STATE_FAILED, STATE_CANCELLED})

#: Refusal codes (the API maps them to HTTP statuses).
REFUSAL_QUEUE_FULL = "analysis_queue_full"
REFUSAL_OWNER_LIMIT = "analysis_owner_limit"

#: How often an idle worker wakes to purge expired finished results, so a
#: result is dropped at about its TTL even when nobody polls or submits.
SWEEP_INTERVAL_SECONDS = 60.0

#: How long `shutdown` waits for a worker to leave its running job.
SHUTDOWN_JOIN_SECONDS = 5.0


class JobCancelled(Exception):
    """Raised by a job's run callable (via `JobContext.check_cancelled`) to stop early."""


class QueueRefused(Exception):
    """A submission was refused (never an eviction of someone else's job).

    ``code`` is one of the ``REFUSAL_*`` constants; ``queue_length`` and
    ``limit`` describe the bound that was hit.
    """

    def __init__(self, code: str, *, queue_length: int, limit: int) -> None:
        super().__init__(f"{code}: {queue_length}/{limit}")
        self.code = code
        self.queue_length = queue_length
        self.limit = limit


@dataclass
class Job:
    id: str
    status: str = STATE_QUEUED
    total: int = 0
    completed: int = 0
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    #: Fairness/authorization key: account `player_uuid` or `anon:<digest>` (PLR-9b); never serialized.
    owner: Optional[str] = None
    kind: str = "dynamic_analysis"
    #: The work. Dropped when the job finishes so a kept result does not pin its input (a whole deck).
    run: Optional[Callable[["JobContext"], dict[str, Any]]] = field(default=None, repr=False, compare=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def to_dict(self, queue_position: Optional[int] = None, queue_length: Optional[int] = None) -> dict[str, Any]:
        return {
            "jobId": self.id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "result": self.result,
            "error": self.error,
            "queuePosition": queue_position,
            "queueLength": queue_length,
        }


class JobContext:
    """What a running job's callable gets: progress reporting and cancellation."""

    def __init__(self, job: Job) -> None:
        self._job = job

    def report(self, completed: int, total: int) -> None:
        self._job.completed = completed
        self._job.total = total

    def cancelled(self) -> bool:
        return self._job.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise JobCancelled()


class JobStore:
    """In-memory job state: all jobs, fair pending queue, retention (see module docstring)."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        #: owner -> that owner's pending jobs (FIFO). Insertion order of the owners is the
        #: round-robin rotation; the owner served moves to the back.
        self._pending: "OrderedDict[Optional[str], deque[Job]]" = OrderedDict()
        self._running_per_owner: dict[Optional[str], int] = {}
        #: owner -> ids of that owner's finished jobs, oldest first.
        self._finished: dict[Optional[str], deque[str]] = {}

    # -- pending -----------------------------------------------------------

    def pending_count(self) -> int:
        return sum(len(q) for q in self._pending.values())

    def owner_active_count(self, owner: Optional[str]) -> int:
        """Queued plus running jobs of ``owner``."""
        return len(self._pending.get(owner, ())) + self._running_per_owner.get(owner, 0)

    def enqueue(self, job: Job) -> None:
        self.jobs[job.id] = job
        self._pending.setdefault(job.owner, deque()).append(job)

    def pop_next(self) -> Optional[Job]:
        """The next job in round-robin order across owners, or None."""
        if not self._pending:
            return None
        owner = next(iter(self._pending))
        queue_ = self._pending[owner]
        job = queue_.popleft()
        if queue_:
            self._pending.move_to_end(owner)
        else:
            del self._pending[owner]
        return job

    def remove_pending(self, job: Job) -> bool:
        queue_ = self._pending.get(job.owner)
        if queue_ is None or job not in queue_:
            return False
        queue_.remove(job)
        if not queue_:
            del self._pending[job.owner]
        return True

    def dispatch_order(self) -> list[Job]:
        """Pending jobs in the exact order `pop_next` would hand them out."""
        queues = [deque(q) for q in self._pending.values()]
        order: list[Job] = []
        while queues:
            remaining = []
            for q in queues:
                order.append(q.popleft())
                if q:
                    remaining.append(q)
            queues = remaining
        return order

    def position(self, job: Job) -> Optional[int]:
        """1-based place in the dispatch order, None if not pending."""
        for index, queued in enumerate(self.dispatch_order()):
            if queued is job:
                return index + 1
        return None

    # -- running / finished ------------------------------------------------

    def mark_running(self, job: Job) -> None:
        self._running_per_owner[job.owner] = self._running_per_owner.get(job.owner, 0) + 1

    def mark_not_running(self, job: Job) -> None:
        left = self._running_per_owner.get(job.owner, 0) - 1
        if left > 0:
            self._running_per_owner[job.owner] = left
        else:
            self._running_per_owner.pop(job.owner, None)

    def record_finished(self, job: Job, results_per_owner: int) -> None:
        """File a finished job under its owner; roll that owner's own oldest results off."""
        finished = self._finished.setdefault(job.owner, deque())
        finished.append(job.id)
        while len(finished) > results_per_owner:
            self.jobs.pop(finished.popleft(), None)

    def purge_expired(self, now: float, ttl: float) -> int:
        purged = 0
        for owner in list(self._finished):
            finished = self._finished[owner]
            while finished:
                job = self.jobs.get(finished[0])
                if job is not None and (job.finished_at or 0.0) + ttl > now:
                    break
                self.jobs.pop(finished.popleft(), None)
                purged += 1
            if not finished:
                del self._finished[owner]
        return purged


class JobRunner:
    """Admission, fair dispatch into ``workers`` slots, cancellation, retention, shutdown."""

    def __init__(
        self,
        workers: int,
        *,
        queue_max: int,
        per_owner_max: int,
        results_per_owner: int,
        result_ttl_seconds: float,
        clock: Callable[[], float] = time.time,
        start_threads: bool = True,
        store: Optional[JobStore] = None,
    ) -> None:
        self.num_workers = workers
        self.queue_max = queue_max
        self.per_owner_max = per_owner_max
        self.results_per_owner = results_per_owner
        self.result_ttl_seconds = result_ttl_seconds
        self._clock = clock
        self._store = store if store is not None else JobStore()
        self._cond = threading.Condition()
        self._stopped = False
        self._threads: list[threading.Thread] = []
        if start_threads:
            for i in range(workers):
                thread = threading.Thread(target=self._worker_loop, name=f"job-runner-{i}", daemon=True)
                thread.start()
                self._threads.append(thread)

    # -- public ------------------------------------------------------------

    def submit(
        self,
        owner: Optional[str],
        run: Callable[[JobContext], dict[str, Any]],
        *,
        total: int = 0,
        kind: str = "dynamic_analysis",
    ) -> Job:
        """Queue a job, or raise `QueueRefused` (nobody's job is ever evicted)."""
        with self._cond:
            if self._stopped:
                raise QueueRefused(REFUSAL_QUEUE_FULL, queue_length=0, limit=0)
            self._purge_locked()
            if self._store.owner_active_count(owner) >= self.per_owner_max:
                raise QueueRefused(
                    REFUSAL_OWNER_LIMIT, queue_length=self._store.owner_active_count(owner), limit=self.per_owner_max
                )
            if self._store.pending_count() >= self.queue_max:
                raise QueueRefused(REFUSAL_QUEUE_FULL, queue_length=self._store.pending_count(), limit=self.queue_max)
            job = Job(id=str(uuid.uuid4()), total=total, owner=owner, kind=kind, run=run, created_at=self._clock())
            self._store.enqueue(job)
            self._cond.notify()
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._cond:
            self._purge_locked()
            return self._store.jobs.get(job_id)

    def view(self, job: Job) -> dict[str, Any]:
        """The poll payload: the job plus its queue position while queued."""
        with self._cond:
            if job.status == STATE_QUEUED:
                return job.to_dict(self._store.position(job), self._store.pending_count())
            return job.to_dict()

    def cancel(self, job_id: str, owner: Optional[str]) -> Optional[Job]:
        """Cancel a queued or running job of ``owner``. None when unknown or foreign (404)."""
        with self._cond:
            job = self._store.jobs.get(job_id)
            if job is None or job.owner != owner:
                return None
            if job.status == STATE_QUEUED:
                self._store.remove_pending(job)
                self._finish_locked(job, STATE_CANCELLED)
            elif job.status == STATE_RUNNING:
                job.cancel_event.set()
                self._finish_locked(job, STATE_CANCELLED)
            return job

    def sweep(self) -> int:
        """Purge finished results older than the TTL; returns how many."""
        with self._cond:
            return self._purge_locked()

    def run_next(self) -> Optional[Job]:
        """Run the next fair job on the calling thread (deterministic tests); None if idle."""
        with self._cond:
            job = self._take_locked()
        if job is not None:
            self._execute(job)
        return job

    def shutdown(self) -> None:
        """Drop queued jobs, cancel running ones, stop the workers. Idempotent."""
        with self._cond:
            if self._stopped:
                return
            self._stopped = True
            while True:
                job = self._store.pop_next()
                if job is None:
                    break
                self._finish_locked(job, STATE_CANCELLED, error="shutdown")
            for job in list(self._store.jobs.values()):
                if job.status == STATE_RUNNING:
                    job.cancel_event.set()
            self._cond.notify_all()
        for thread in self._threads:
            thread.join(SHUTDOWN_JOIN_SECONDS)

    # -- internals ---------------------------------------------------------

    def _purge_locked(self) -> int:
        return self._store.purge_expired(self._clock(), self.result_ttl_seconds)

    def _take_locked(self) -> Optional[Job]:
        job = self._store.pop_next()
        if job is not None:
            job.status = STATE_RUNNING
            job.started_at = self._clock()
            self._store.mark_running(job)
        return job

    def _finish_locked(self, job: Job, status: str, *, error: Optional[str] = None) -> None:
        """Move a job to a finished state exactly once and file it for retention."""
        if job.status in FINISHED_STATES:
            return
        was_running = job.status == STATE_RUNNING
        job.status = status
        job.finished_at = self._clock()
        if error is not None:
            job.error = error
        job.run = None
        if was_running:
            self._store.mark_not_running(job)
        self._store.record_finished(job, self.results_per_owner)

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                job = None
                while not self._stopped:
                    job = self._take_locked()
                    if job is not None:
                        break
                    self._cond.wait(SWEEP_INTERVAL_SECONDS)
                    self._purge_locked()
                if job is None:
                    return
            self._execute(job)

    def _execute(self, job: Job) -> None:
        run = job.run
        status, result, error = STATE_FAILED, None, None
        try:
            if run is None or job.cancel_event.is_set():
                raise JobCancelled()
            result = run(JobContext(job))
            status = STATE_DONE
        except JobCancelled:
            status = STATE_CANCELLED
        except Exception as exc:  # noqa: BLE001 - a job failing must not kill its worker
            logger.exception("job %s (%s) failed", job.id, job.kind)
            error = str(exc)
        with self._cond:
            if job.status == STATE_RUNNING:  # not already cancelled/dropped while it ran
                if status == STATE_DONE:
                    job.result = result
                self._finish_locked(job, status, error=error)
            else:
                job.run = None

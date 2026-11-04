"""Allowlisted database-update jobs for the admin page (PLR-9d / PLR-17, plan section 6).

Only the kinds registered in `JOB_KINDS` can be started: there is no arbitrary command, SQL
or path. A job runs once in a background thread, exposes bounded progress lines, and has a
job-bound **poll token** (random, only its digest kept, valid until the job is evicted) so the
page can follow progress without asking for the password again. The token reads one job and
nothing else.

In-memory and per process, like `DynamicAnalysisJobs`: a job has no meaning across a restart.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from mtg_analyzer import config

#: Job kinds the admin may start (plan section 6 "allowlisted DB refresh/update jobs").
KIND_CARD_POOL = "card-pool"
KIND_COMBOS = "combos"
JOB_KINDS = (KIND_CARD_POOL, KIND_COMBOS)

STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"

#: Seconds the card-pool script may run (same limit the former synchronous route used).
CARD_POOL_TIMEOUT_SECONDS = 15 * 60

_CARD_POOL_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "update_card_pool.py"

#: Bytes of entropy of a poll token (256 bits, like every other secret here).
POLL_TOKEN_BYTES = 32


class JobAlreadyRunning(Exception):
    pass


class UnknownJobKind(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    started_by: str
    started_at: float
    token_digest: str
    state: str = STATE_RUNNING
    finished_at: Optional[float] = None
    lines: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None

    def view(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "state": self.state, "started_at": self.started_at,
            "finished_at": self.finished_at, "progress": list(self.lines), "result": self.result,
            "error": self.error,
        }


Reporter = Callable[[str], None]
Runner = Callable[[Reporter], dict]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def run_card_pool_update(report: Reporter) -> dict:
    """The existing bulk importer, run as a subprocess; its output tail is the progress."""
    process = subprocess.Popen(
        [sys.executable, str(_CARD_POOL_SCRIPT)], cwd=_CARD_POOL_SCRIPT.parent.parent,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    timer = threading.Timer(CARD_POOL_TIMEOUT_SECONDS, process.kill)
    timer.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            report(line)
        code = process.wait()
    finally:
        timer.cancel()
    if code != 0:
        raise RuntimeError(f"update script exited with status {code}")
    return {"updated": True}


def run_combo_update(report: Reporter) -> dict:
    from mtg_analyzer.api.dependencies import get_commander_spellbook_database

    report("Commander Spellbook snapshot herunterladen ...")
    summary = get_commander_spellbook_database().update()
    report("Snapshot importiert.")
    return {"summary": summary}


class AdminJobs:
    def __init__(self, runners: Optional[dict[str, Runner]] = None, clock=time.time) -> None:
        self._runners: dict[str, Runner] = runners if runners is not None else {
            KIND_CARD_POOL: run_card_pool_update,
            KIND_COMBOS: run_combo_update,
        }
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(
        self, kind: str, started_by: str, *, synchronous: bool = False,
        on_finish: Optional[Callable[[Job], None]] = None,
    ) -> tuple[Job, str]:
        """Start ``kind``; returns the job and its raw poll token (shown once).

        One job per kind at a time. ``synchronous`` runs inline (tests); ``on_finish`` is called
        with the finished job (the audit entry)."""
        if kind not in JOB_KINDS or kind not in self._runners:
            raise UnknownJobKind(kind)
        with self._lock:
            self._evict()
            if any(j.kind == kind and j.state == STATE_RUNNING for j in self._jobs.values()):
                raise JobAlreadyRunning(kind)
            token = secrets.token_urlsafe(POLL_TOKEN_BYTES)
            job = Job(str(uuid.uuid4()), kind, started_by, self._clock(), _digest(token))
            self._jobs[job.id] = job
        if synchronous:
            self._run(job, on_finish)
        else:
            threading.Thread(
                target=self._run, args=(job, on_finish), name=f"admin-job-{kind}", daemon=True
            ).start()
        return job, token

    def _run(self, job: Job, on_finish: Optional[Callable[[Job], None]] = None) -> None:
        def report(line: str) -> None:
            text = line.rstrip()[: config.ADMIN_JOB_LOG_LINE_MAX]
            if text:
                with self._lock:
                    job.lines.append(text)
                    del job.lines[: -config.ADMIN_JOB_LOG_LINES]

        try:
            result = self._runners[job.kind](report)
            outcome = (STATE_SUCCEEDED, result, None)
        except Exception as exc:  # noqa: BLE001 - the job reports any failure, it never kills the server
            # Only the exception type: messages can carry paths or URLs; the detail is in the server log.
            outcome = (STATE_FAILED, None, type(exc).__name__)
        with self._lock:
            job.state, job.result, job.error = outcome
            job.finished_at = self._clock()
        if on_finish is not None:
            try:
                on_finish(job)
            except Exception:  # noqa: BLE001 - an audit failure must not change the job's outcome
                pass

    def _evict(self) -> None:
        """Drop finished jobs past retention and keep at most the newest `ADMIN_JOB_HISTORY_MAX`."""
        now = self._clock()
        for job_id in [j.id for j in self._jobs.values()
                       if j.finished_at is not None and now - j.finished_at > config.ADMIN_JOB_RETENTION_SECONDS]:
            del self._jobs[job_id]
        finished = sorted((j for j in self._jobs.values() if j.finished_at is not None), key=lambda j: j.finished_at)
        for job in finished[: max(0, len(finished) - config.ADMIN_JOB_HISTORY_MAX)]:
            del self._jobs[job.id]

    def list(self) -> list[dict]:
        with self._lock:
            self._evict()
            return [j.view() for j in sorted(self._jobs.values(), key=lambda j: -j.started_at)]

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            self._evict()
            job = self._jobs.get(job_id)
            return job.view() if job else None

    def get_with_token(self, job_id: str, token: str) -> Optional[dict]:
        """The job's view when ``token`` is that job's poll token, else None (same as unknown)."""
        if not token:
            return None
        with self._lock:
            self._evict()
            job = self._jobs.get(job_id)
            if job is None or not hmac.compare_digest(job.token_digest, _digest(token)):
                return None
            return job.view()

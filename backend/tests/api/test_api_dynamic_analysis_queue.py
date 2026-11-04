"""ANA-6: queue refusals, queue position, cancel and owner isolation through the API.

The runner has no worker threads here; `run_next()` plays the worker slot, so
every state is deterministic.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_dynamic_analysis_jobs, get_lazy_card_loader
from mtg_analyzer.api.viewer import Viewer, play_viewer, viewer
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.dynamic_analysis import DynamicAnalysisJobs
from mtg_analyzer.services.job_runner import JobRunner
from tests.services.test_dynamic_analysis import LEGAL_DECK, _commander, _FakeLoader, _forest

BODY = {**LEGAL_DECK, "botKind": "goldfish", "numMatches": 1, "maxTurns": 2}
OWNER_HEADER = "x-test-owner"
QUEUE_MAX = 3
PER_OWNER_MAX = 2


class Client:
    """A caller with its own owner key, so the tests do not depend on the auth mode."""

    _count = 0

    def __init__(self):
        Client._count += 1
        self.http = TestClient(app, headers={OWNER_HEADER: f"owner-{Client._count}"})

    def __getattr__(self, name):
        return getattr(self.http, name)


def _fake_viewer(request: Request) -> Viewer:
    return Viewer(None, request.headers.get(OWNER_HEADER))


@pytest.fixture
def world():
    runner = JobRunner(
        1, queue_max=QUEUE_MAX, per_owner_max=PER_OWNER_MAX, results_per_owner=5,
        result_ttl_seconds=3600, start_threads=False,
    )
    jobs = DynamicAnalysisJobs(runner=runner)
    loader = _FakeLoader({"Forest": _forest(), "Test Commander": _commander()})
    app.dependency_overrides[get_deck_database] = lambda: DeckDatabase()
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    app.dependency_overrides[get_dynamic_analysis_jobs] = lambda: jobs
    app.dependency_overrides[viewer] = _fake_viewer
    app.dependency_overrides[play_viewer] = _fake_viewer
    yield jobs, runner
    for dep in (get_deck_database, get_lazy_card_loader, get_dynamic_analysis_jobs, viewer, play_viewer):
        app.dependency_overrides.pop(dep, None)


def start(client):
    return client.post("/api/analysis/dynamic", json=BODY)


def test_queued_poll_reports_position_then_progress_and_result(world):
    _, runner = world
    alice, bob = Client(), Client()
    first = start(alice).json()["jobId"]
    second = start(bob).json()["jobId"]
    polled = bob.get(f"/api/analysis/dynamic/{second}").json()
    assert polled["status"] == "queued" and polled["queuePosition"] == 2 and polled["queueLength"] == 2
    runner.run_next()
    assert alice.get(f"/api/analysis/dynamic/{first}").json()["status"] == "done"
    assert bob.get(f"/api/analysis/dynamic/{second}").json()["queuePosition"] == 1
    runner.run_next()
    done = bob.get(f"/api/analysis/dynamic/{second}").json()
    assert done["status"] == "done" and done["queuePosition"] is None and done["result"]["matchesRun"] == 1


def test_owner_limit_is_429_with_code_and_retry_after(world):
    alice = Client()
    for _ in range(PER_OWNER_MAX):
        assert start(alice).status_code == 200
    refused = start(alice)
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "analysis_owner_limit"
    assert int(refused.headers["Retry-After"]) > 0
    assert start(Client()).status_code == 200  # others are not affected


def test_full_queue_is_503_and_nothing_is_evicted(world):
    _, runner = world
    clients = [Client() for _ in range(QUEUE_MAX + 1)]
    ids = [start(c).json()["jobId"] for c in clients[:QUEUE_MAX]]
    refused = start(clients[-1])
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "analysis_queue_full"
    assert "Retry-After" in refused.headers
    for client, job_id in zip(clients, ids):
        assert client.get(f"/api/analysis/dynamic/{job_id}").json()["status"] == "queued"


def test_cancel_is_owner_only_and_removes_the_job_from_the_queue(world):
    _, runner = world
    alice, bob = Client(), Client()
    job_id = start(alice).json()["jobId"]
    other = start(bob).json()["jobId"]
    assert bob.delete(f"/api/analysis/dynamic/{job_id}").status_code == 404  # foreign = missing
    assert Client().delete(f"/api/analysis/dynamic/{job_id}").status_code == 404
    assert alice.get(f"/api/analysis/dynamic/{job_id}").json()["status"] == "queued"
    cancelled = alice.delete(f"/api/analysis/dynamic/{job_id}")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert bob.get(f"/api/analysis/dynamic/{other}").json()["queuePosition"] == 1
    runner.run_next()
    assert alice.get(f"/api/analysis/dynamic/{job_id}").json()["status"] == "cancelled"
    assert alice.delete("/api/analysis/dynamic/unknown").status_code == 404


def test_foreign_poll_is_404(world):
    job_id = start(Client()).json()["jobId"]
    assert Client().get(f"/api/analysis/dynamic/{job_id}").status_code == 404


def test_another_owners_flood_never_evicts_a_finished_result(world):
    _, runner = world
    alice = Client()
    job_id = start(alice).json()["jobId"]
    runner.run_next()
    for _ in range(10):
        flooder = Client()
        if start(flooder).status_code == 200:
            runner.run_next()
    assert alice.get(f"/api/analysis/dynamic/{job_id}").json()["status"] == "done"


@pytest.mark.parametrize(
    ("headers", "needle"),
    [
        ({}, "Warteschlange"),  # VIS-24: German is the default language
        ({"Cookie": "mtg_lang=en"}, "analysis queue is full"),
        ({"Accept-Language": "en-GB,en;q=0.8,de;q=0.5"}, "analysis queue is full"),
        ({"Cookie": "mtg_lang=de", "Accept-Language": "en"}, "Warteschlange"),  # the cookie wins
    ],
)
def test_queue_refusal_message_follows_the_callers_language(world, headers, needle):
    clients = [Client() for _ in range(QUEUE_MAX + 1)]
    for client in clients[:QUEUE_MAX]:
        assert start(client).status_code == 200
    refused = clients[-1].post("/api/analysis/dynamic", json=BODY, headers=headers)
    detail = refused.json()["detail"]
    assert detail["code"] == "analysis_queue_full"  # the code never changes with the language
    assert needle in detail["message"]

"""Tests for ANA-4: the headless goldfish-simulation harness + its API.

Reference: mtg_analyzer/services/dynamic_analysis.py,
mtg_analyzer/api/dynamic_analysis.py, docs/implementation-state/BACKLOG.md
"ANA-4".
"""

import time

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_dynamic_analysis_jobs, get_lazy_card_loader
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.dynamic_analysis import (
    PER_TURN_METRICS,
    DynamicAnalysisJobs,
    run_dynamic_analysis,
    run_one_match,
)
from mtg_analyzer.services.bots import GoldfishBot, GreedyBot
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _forest(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _commander():
    return Card(
        id="Test Commander",
        name="Test Commander",
        type_line="Legendary Creature — Elf",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )


def _library(n_lands=60):
    return [_forest()] * n_lands


class TestRunOneMatch:
    def test_goldfish_bot_plays_a_land_every_turn(self):
        result = run_one_match(_library(), None, bot=GoldfishBot("p1"), max_turns=5)
        assert result.turns_reached == 5
        # One snapshot per turn that was reached.
        assert set(result.per_turn) == {1, 2, 3, 4, 5}
        for turn, snapshot in result.per_turn.items():
            assert set(snapshot) == set(PER_TURN_METRICS)
            # A land-only deck: lands drawn only grows, tracking the turn.
            assert snapshot["lands_drawn"] >= turn

    def test_greedy_bot_casts_the_commander(self):
        result = run_one_match([_forest()] * 60, [_commander()], bot=GreedyBot("p1"), max_turns=5)
        assert "Test Commander" in result.commander_turns
        assert 1 <= result.commander_turns["Test Commander"] <= 5

    def test_stops_at_max_turns_without_hanging(self):
        # A generous max_turns still terminates promptly (regression guard
        # for the `advance_to_decision` vs. `pass_priority` fallback — see
        # this module's own docstring for why the naive fallback spins
        # forever in solo/goldfish mode).
        result = run_one_match(_library(), None, bot=GoldfishBot("p1"), max_turns=12)
        assert result.turns_reached == 12

    def test_infinite_mana_guard_aborts_the_match(self, monkeypatch):
        # Exercises the real detection path (`GameState.mana_produced_
        # this_turn`) against an ordinary, finite land-only deck rather than
        # constructing a genuine combo: lowering the threshold below what a
        # `GreedyBot` legitimately taps for in a few turns triggers the same
        # code a real infinite-mana deck would.
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis, "INFINITE_MANA_THRESHOLD", 3)
        result = run_one_match(_library(), None, bot=GreedyBot("p1"), max_turns=10)
        assert result.aborted_infinite_mana is True
        # Ends well short of max_turns — the whole point of the guard.
        assert result.turns_reached < 10
        # The turn the abort happened on is dropped entirely — its
        # `mana_produced` reading is exactly the number that triggered it.
        assert result.turns_reached not in result.per_turn


class TestRunDynamicAnalysis:
    def test_aggregates_mean_and_stddev_per_turn(self):
        result = run_dynamic_analysis(
            _library(), None, bot_kind="goldfish", num_matches=4, max_turns=4,
        )
        assert result.matches_run == 4
        assert len(result.per_turn) == 4
        for row in result.per_turn:
            assert 1 <= row["turn"] <= 4
            for metric in PER_TURN_METRICS:
                stat = row[metric]
                assert stat["n"] == 4
                assert isinstance(stat["mean"], float)
                assert stat["stddev"] >= 0.0

    def test_a_normal_game_reads_zero_card_advantage(self):
        # RULE 103.7a's skipped first draw is baked into the baseline (see
        # `run_one_match`'s `maybe_sample`), so a plain land-only deck with
        # no draw effects should read exactly 0, not a constant offset.
        result = run_dynamic_analysis(_library(), None, bot_kind="goldfish", num_matches=2, max_turns=3)
        for row in result.per_turn:
            assert row["card_advantage"]["mean"] == 0.0

    def test_unknown_bot_kind_raises(self):
        import pytest

        with pytest.raises(ValueError):
            run_dynamic_analysis(_library(), None, bot_kind="nope", num_matches=1, max_turns=1)

    def test_clamps_out_of_range_request(self, monkeypatch):
        # Exercises the clamp against a request that exceeds the real
        # bounds without actually running 200 x 30-turn matches (each
        # `apply_action` snapshots a full `GameState.clone()` for undo, so
        # that combination is genuinely slow, not just a big loop) — lower
        # the bounds themselves instead, so an out-of-range request stays
        # cheap to simulate here.
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis, "MAX_NUM_MATCHES", 2)
        monkeypatch.setattr(dynamic_analysis, "MAX_MAX_TURNS", 2)
        result = run_dynamic_analysis(
            _library(), None, bot_kind="goldfish", num_matches=10_000, max_turns=10_000,
        )
        assert result.matches_requested == 2
        assert result.max_turns == 2


class TestDynamicAnalysisJobs:
    def test_job_runs_in_background_and_completes(self):
        jobs = DynamicAnalysisJobs()
        job_id = jobs.start(_library(), None, bot_kind="goldfish", num_matches=3, max_turns=3)

        deadline = time.time() + 10
        job = jobs.get(job_id)
        while job.status == "running" and time.time() < deadline:
            time.sleep(0.02)
            job = jobs.get(job_id)

        assert job.status == "done"
        assert job.completed == job.total == 3
        assert job.result["matchesRun"] == 3

    def test_unknown_job_id_is_none(self):
        jobs = DynamicAnalysisJobs()
        assert jobs.get("does-not-exist") is None


# -- API ----------------------------------------------------------------


class _FakeLoader:
    """Resolves a fixed set of names without touching Scryfall."""

    def __init__(self, cards: dict[str, Card]) -> None:
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        not_found = [n for n in names if n not in self._cards]
        return LoadCardsResult(cards=found, not_found=not_found)


#: A structurally + Commander-legal deck (1 commander + 99 basics).
LEGAL_DECK = {
    "commanderText": "1 Test Commander\n",
    "mainboardText": "99 Forest\n",
}


def _setup():
    deck_db = DeckDatabase()
    jobs = DynamicAnalysisJobs()
    loader = _FakeLoader({"Forest": _forest(), "Test Commander": _commander()})
    app.dependency_overrides[get_deck_database] = lambda: deck_db
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    app.dependency_overrides[get_dynamic_analysis_jobs] = lambda: jobs
    return deck_db, jobs


def _teardown():
    for dep in (get_deck_database, get_lazy_card_loader, get_dynamic_analysis_jobs):
        app.dependency_overrides.pop(dep, None)


class TestDynamicAnalysisApi:
    def teardown_method(self):
        _teardown()

    def test_start_and_poll_to_completion(self):
        _setup()
        client = TestClient(app)
        start = client.post(
            "/api/analysis/dynamic",
            json={**LEGAL_DECK, "botKind": "goldfish", "numMatches": 3, "maxTurns": 3},
        )
        assert start.status_code == 200
        job_id = start.json()["jobId"]

        deadline = time.time() + 10
        body = {"status": "running"}
        while body["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            body = client.get(f"/api/analysis/dynamic/{job_id}").json()

        assert body["status"] == "done"
        assert body["result"]["matchesRun"] == 3
        assert len(body["result"]["perTurn"]) == 3

    def test_illegal_deck_is_rejected_before_starting_a_job(self):
        _setup()
        client = TestClient(app)
        response = client.post(
            "/api/analysis/dynamic",
            json={"mainboardText": "99 Forest\n", "botKind": "goldfish", "numMatches": 1, "maxTurns": 1},
        )
        assert response.status_code == 422

    def test_unknown_bot_kind_is_rejected(self):
        _setup()
        client = TestClient(app)
        response = client.post(
            "/api/analysis/dynamic",
            json={**LEGAL_DECK, "botKind": "nope", "numMatches": 1, "maxTurns": 1},
        )
        assert response.status_code == 422

    def test_unknown_job_id_is_404(self):
        _setup()
        client = TestClient(app)
        response = client.get("/api/analysis/dynamic/does-not-exist")
        assert response.status_code == 404

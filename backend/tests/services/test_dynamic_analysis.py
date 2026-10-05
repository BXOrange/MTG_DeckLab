"""Tests for ANA-4: the headless goldfish-simulation harness + its API.

Reference: mtg_analyzer/services/dynamic_analysis.py,
mtg_analyzer/api/dynamic_analysis.py, docs/implementation-state/BACKLOG.md
"ANA-4".
"""

import time

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_dynamic_analysis_jobs, get_lazy_card_loader
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.dynamic_analysis import (
    PER_TURN_METRICS,
    DynamicAnalysisJobs,
    run_dynamic_analysis,
    run_one_match,
)
from mtg_analyzer.services.bots import GoldfishBot, GreedyBot, ManaMaximizerBot
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


def _cheap_creature(name="Test Spell"):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Elf",
        mana_cost_string="{G}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
        color_identity={"G"},
    )


def _big_beater(name, cmc, power):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Elf",
        mana_cost_string=(f"{{{cmc - 1}}}{{G}}" if cmc > 1 else "{G}"),
        converted_mana_cost=cmc,
        is_creature=True,
        power=power,
        toughness=cmc,
        color_identity={"G"},
    )


def _aggressive_library(n_lands=38, n_creatures=22):
    # High power relative to toughness/cost: a GreedyBot attacking with
    # these every turn would kill a real 40-life dummy within a handful of
    # turns — the exact scenario `DUMMY_ANALYSIS_LIFE` (dynamic_analysis.py)
    # exists to neutralize. See TestRunDynamicAnalysis's survivorship-bias
    # regression test below.
    lands = [_forest()] * n_lands
    creatures = [_big_beater(f"Bear {i}", 2 + (i % 3), 6 + (i % 3)) for i in range(n_creatures)]
    return lands + creatures


def _library_with_favorite_on_top(name="Test Spell", n_lands=39):
    # `Player.draw` pops from the *end* of the list (models/player.py:
    # "top of deck"), so the favorite card goes last to guarantee it's the
    # very first card drawn — deterministic without relying on shuffling.
    return [_forest()] * n_lands + [_cheap_creature(name)]


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

    def test_smart_bot_can_take_two_mulligans_and_counts_them(self):
        from mtg_analyzer.services.bots import SmartBot

        result = run_one_match(_library(), None, bot=SmartBot("p1"), max_turns=1)
        assert result.mulligans_taken == 2

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
        # Recorded separately so the aggregate can report "usually goes
        # infinite around turn N" rather than a bare yes/no.
        assert result.aborted_turn == result.turns_reached

    def test_greedy_bot_draws_and_casts_a_favorite_card(self):
        result = run_one_match(
            _library_with_favorite_on_top(),
            None,
            bot=GreedyBot("p1"),
            max_turns=3,
            favorite_card_names={"Test Spell"},
        )
        favorite = result.favorite_cards["Test Spell"]
        assert favorite["drawn_turn"] == 1
        # A GreedyBot casts anything affordable the instant it can (services
        # /bots.py) — an untapped Forest and a {G} creature in the opening
        # hand means it's cast turn 1.
        assert favorite["cast_turn"] == 1
        assert favorite["castable_turn"] == 1

    def test_goldfish_bot_never_casts_a_favorite_nonland_card(self):
        # The documented degenerate case (see dynamic_analysis.py's
        # docstring on `GoldfishBot`): it plays a land per turn and
        # otherwise passes, so a favorite nonland card is drawn and
        # castable but never actually cast.
        result = run_one_match(
            _library_with_favorite_on_top(),
            None,
            bot=GoldfishBot("p1"),
            max_turns=3,
            favorite_card_names={"Test Spell"},
        )
        favorite = result.favorite_cards["Test Spell"]
        assert favorite["drawn_turn"] == 1
        assert favorite["cast_turn"] is None
        assert favorite["castable_turn"] == 1

    def test_no_favorite_card_names_yields_empty_dict(self):
        result = run_one_match(_library(), None, bot=GoldfishBot("p1"), max_turns=2)
        assert result.favorite_cards == {}

    def test_combo_turn_is_recorded_when_its_cards_are_on_battlefield(self):
        combo_cards = [_cheap_creature("Combo A"), _cheap_creature("Combo B")]
        combo_specs = [
            {
                "id": "assembled",
                "uses": [
                    {"name": "Combo A", "quantity": 1},
                    {"name": "Combo B", "quantity": 1},
                ],
            },
            {"id": "not-assembled", "uses": [{"name": "Never Drawn", "quantity": 1}]},
        ]
        result = run_one_match(
            [_forest()] * 38 + combo_cards,
            None,
            bot=GreedyBot("p1"),
            max_turns=4,
            combo_specs=combo_specs,
        )
        assert result.combo_turns["assembled"] == 2
        assert "not-assembled" not in result.combo_turns

    def test_aggressive_deck_does_not_end_the_match_early(self):
        # `DUMMY_ANALYSIS_LIFE` gives the dummy far more than a real game's
        # 40 life specifically so a `GreedyBot` attacking every turn with
        # a deck this aggressive still reaches `max_turns` rather than
        # ending the match (and truncating its per-turn samples) the
        # moment the dummy dies.
        result = run_one_match(_aggressive_library(), None, bot=GreedyBot("p1"), max_turns=8)
        assert result.turns_reached == 8
        assert set(result.per_turn) == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_mana_maximizer_bot_taps_out_without_casting(self):
        # A cheap castable creature is drawn turn 1 (see
        # `_library_with_favorite_on_top`'s guaranteed-top-of-library
        # trick) — `ManaMaximizerBot` should still never cast it, only
        # play its land and tap it for mana.
        result = run_one_match(
            _library_with_favorite_on_top(),
            None,
            bot=ManaMaximizerBot("p1"),
            max_turns=1,
            favorite_card_names={"Test Spell"},
        )
        favorite = result.favorite_cards["Test Spell"]
        assert favorite["drawn_turn"] == 1
        assert favorite["cast_turn"] is None
        # The one land played that turn was tapped for mana rather than
        # left untapped, so "mana produced" matches "mana potential"
        # exactly — the whole point of this bot.
        assert result.per_turn[1]["mana_produced"] == result.per_turn[1]["mana_potential"]
        assert result.per_turn[1]["mana_produced"] == 1.0


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

    def test_infinite_mana_turn_is_aggregated_across_aborted_matches(self, monkeypatch):
        # Same threshold-lowering trick as TestRunOneMatch's guard test,
        # but through the aggregate: `infinite_mana_turn` should read the
        # mean/stddev of the turn each aborted match was cut short on, with
        # `n` equal to `matches_aborted_infinite_mana` (every match aborts
        # here, so both are `matches_run`).
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis, "INFINITE_MANA_THRESHOLD", 3)
        result = run_dynamic_analysis(
            _library(), None, bot_kind="greedy", num_matches=3, max_turns=10,
        )
        assert result.matches_aborted_infinite_mana == result.matches_run
        assert result.infinite_mana_turn["n"] == result.matches_aborted_infinite_mana
        assert result.infinite_mana_turn["mean"] > 0.0
        assert result.infinite_mana_turn["stddev"] >= 0.0

    def test_infinite_mana_turn_is_zero_n_when_no_match_aborts(self):
        result = run_dynamic_analysis(_library(), None, bot_kind="goldfish", num_matches=2, max_turns=3)
        assert result.matches_aborted_infinite_mana == 0
        assert result.infinite_mana_turn == {"mean": 0.0, "stddev": 0.0, "n": 0}

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

    def test_favorite_card_fractions_with_greedy_bot(self, monkeypatch):
        # run_dynamic_analysis reshuffles a fresh copy per match (by design
        # — see its own docstring), which would defeat
        # `_library_with_favorite_on_top`'s deterministic ordering; disable
        # just the shuffle so every match sees the same guaranteed draw.
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis.random, "shuffle", lambda seq: None)
        result = run_dynamic_analysis(
            _library_with_favorite_on_top(),
            None,
            bot_kind="greedy",
            num_matches=3,
            max_turns=3,
            favorite_card_names={"Test Spell"},
        )
        stats = result.favorite_cards["Test Spell"]
        assert stats.drawn_fraction == 1.0
        assert stats.cast_fraction == 1.0
        assert stats.cast_turn["mean"] == 1.0
        assert stats.castable_but_never_cast_fraction == 0.0

    def test_favorite_card_fractions_with_goldfish_bot(self, monkeypatch):
        # Mirrors the single-match degenerate case in TestRunOneMatch,
        # aggregated: with the passive bot every drawn nonland favorite
        # reads as "castable but never cast", not "cast". Shuffle disabled
        # for the same reason as the greedy-bot test above.
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis.random, "shuffle", lambda seq: None)
        result = run_dynamic_analysis(
            _library_with_favorite_on_top(),
            None,
            bot_kind="goldfish",
            num_matches=3,
            max_turns=3,
            favorite_card_names={"Test Spell"},
        )
        stats = result.favorite_cards["Test Spell"]
        assert stats.drawn_fraction == 1.0
        assert stats.cast_fraction == 0.0
        assert stats.castable_but_never_cast_fraction == 1.0

    def test_no_favorite_card_names_yields_empty_dict(self):
        result = run_dynamic_analysis(_library(), None, bot_kind="goldfish", num_matches=2, max_turns=2)
        assert result.favorite_cards == {}

    def test_aggregates_any_combo_separately_from_each_combo(self, monkeypatch):
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis.random, "shuffle", lambda seq: None)
        combo_specs = [
            {"id": "present", "uses": [{"name": "Test Spell", "quantity": 1}]},
            {"id": "absent", "uses": [{"name": "Never Drawn", "quantity": 1}]},
        ]
        result = run_dynamic_analysis(
            _library_with_favorite_on_top(),
            None,
            bot_kind="greedy",
            num_matches=2,
            max_turns=3,
            combo_specs=combo_specs,
        )
        stats = {combo["id"]: combo for combo in result.to_dict()["comboStats"]}
        assert stats["present"]["assembledFraction"] == 1.0
        assert stats["present"]["assembledTurn"]["mean"] == 1.0
        assert stats["absent"]["assembledFraction"] == 0.0
        assert stats["absent"]["assembledTurn"]["n"] == 0
        assert result.any_combo_stats["assembledFraction"] == 1.0
        assert result.any_combo_stats["assembledTurn"]["mean"] == 1.0

    def test_aggregates_mulligan_mean_and_distribution(self):
        result = run_dynamic_analysis(
            _library(), None, bot_kind="smart", num_matches=2, max_turns=1,
        )
        assert result.mulligans_taken == {"mean": 2.0, "stddev": 0.0, "n": 2}
        assert result.mulligan_distribution == {"2": 2}

    def test_goldfish_bot_keeps_without_mulligans(self):
        result = run_dynamic_analysis(
            _library(), None, bot_kind="goldfish", num_matches=2, max_turns=1,
        )
        assert result.mulligans_taken == {"mean": 0.0, "stddev": 0.0, "n": 2}
        assert result.mulligan_distribution == {"0": 2}

    def test_aggressive_deck_does_not_lose_later_turn_samples(self):
        # Regression test for a real survivorship-bias bug: before
        # `DUMMY_ANALYSIS_LIFE` (dynamic_analysis.py), a `GreedyBot`
        # attacking every turn with an aggressive deck killed the (real
        # 40-life) dummy within a handful of turns for most matches —
        # which ended those matches' data collection right there. The
        # matches still reaching a later turn were disproportionately the
        # *slower*-developing ones, dragging metrics like "lands drawn"
        # down turn over turn even though every single match's own count
        # only ever increases — reproduced empirically (40 matches, this
        # exact deck shape) before the fix: turn 6 had `n=8`, turn 7 had
        # `n=3`, and the "lands drawn" mean dropped from turn 6 to 7.
        result = run_dynamic_analysis(
            _aggressive_library(n_creatures=10), None, bot_kind="greedy", num_matches=8, max_turns=6,
        )
        assert result.matches_run == 8
        lands_drawn_means = [row["lands_drawn"]["mean"] for row in result.per_turn]
        for row in result.per_turn:
            # No turn should have lost a single match's worth of samples —
            # every match reaches every turn up to max_turns now.
            assert row["lands_drawn"]["n"] == 8
        for earlier, later in zip(lands_drawn_means, lands_drawn_means[1:]):
            assert later >= earlier


class TestDynamicAnalysisJobs:
    def test_job_runs_in_background_and_completes(self):
        jobs = DynamicAnalysisJobs()
        job_id = jobs.start(_library(), None, bot_kind="goldfish", num_matches=3, max_turns=3)

        deadline = time.time() + 10
        job = jobs.get(job_id)
        while job.status in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
            job = jobs.get(job_id)

        assert job.status == "done"
        assert job.completed == job.total == 3
        assert job.result["matchesRun"] == 3

    def test_unknown_job_id_is_none(self):
        jobs = DynamicAnalysisJobs()
        assert jobs.get("does-not-exist") is None

    def test_worker_pool_bounds_concurrent_jobs(self):
        # A single-worker pool must never run two jobs at once: the second
        # job stays "queued" for as long as the first is still "running",
        # proving jobs actually wait their turn in the pool's queue rather
        # than each getting its own thread immediately (the pre-worker-pool
        # behavior this replaces).
        jobs = DynamicAnalysisJobs(num_workers=1)
        first_id = jobs.start(_library(), None, bot_kind="goldfish", num_matches=5, max_turns=5)
        second_id = jobs.start(_library(), None, bot_kind="goldfish", num_matches=5, max_turns=5)

        # Give the pool's single worker a moment to pick up the first job.
        deadline = time.time() + 5
        while jobs.get(first_id).status == "queued" and time.time() < deadline:
            time.sleep(0.01)
        assert jobs.get(first_id).status == "running"
        # The second job can't have started yet — only one worker exists,
        # and it's busy with the first job.
        assert jobs.get(second_id).status == "queued"

        deadline = time.time() + 10
        while jobs.get(first_id).status != "done" and time.time() < deadline:
            time.sleep(0.02)
        assert jobs.get(first_id).status == "done"

        deadline = time.time() + 10
        while jobs.get(second_id).status in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
        assert jobs.get(second_id).status == "done"

    def test_default_worker_count_comes_from_config(self, monkeypatch):
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis.config, "DYNAMIC_ANALYSIS_WORKERS", 3)
        jobs = DynamicAnalysisJobs()
        assert jobs._pool.num_workers == 3

    def test_explicit_worker_count_overrides_config(self, monkeypatch):
        import mtg_analyzer.services.dynamic_analysis as dynamic_analysis

        monkeypatch.setattr(dynamic_analysis.config, "DYNAMIC_ANALYSIS_WORKERS", 3)
        jobs = DynamicAnalysisJobs(num_workers=7)
        assert jobs._pool.num_workers == 7


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
        body = {"status": "queued"}
        while body["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
            body = client.get(f"/api/analysis/dynamic/{job_id}").json()

        assert body["status"] == "done"
        assert body["result"]["matchesRun"] == 3
        assert len(body["result"]["perTurn"]) == 3
        assert body["result"]["anyComboStats"]["assembledFraction"] == 0.0

    def test_combo_specs_are_tracked_through_the_api(self):
        _setup()
        client = TestClient(app)
        start = client.post(
            "/api/analysis/dynamic",
            json={
                **LEGAL_DECK,
                "botKind": "greedy",
                "numMatches": 1,
                "maxTurns": 3,
                "combos": [
                    {"id": "commander-combo", "uses": [{"name": "Test Commander", "quantity": 1}]}
                ],
            },
        )
        assert start.status_code == 200
        job_id = start.json()["jobId"]

        deadline = time.time() + 10
        body = {"status": "queued"}
        while body["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
            body = client.get(f"/api/analysis/dynamic/{job_id}").json()

        assert body["status"] == "done"
        assert body["result"]["comboStats"][0]["id"] == "commander-combo"
        assert body["result"]["comboStats"][0]["assembledFraction"] == 1.0
        assert body["result"]["anyComboStats"]["assembledFraction"] == 1.0

    def test_favorite_cards_from_request_are_tracked(self):
        _setup()
        client = TestClient(app)
        start = client.post(
            "/api/analysis/dynamic",
            json={
                **LEGAL_DECK,
                "botKind": "greedy",
                "numMatches": 2,
                "maxTurns": 2,
                "favoriteCards": ["Test Commander"],
            },
        )
        job_id = start.json()["jobId"]

        deadline = time.time() + 10
        body = {"status": "queued"}
        while body["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
            body = client.get(f"/api/analysis/dynamic/{job_id}").json()

        assert body["status"] == "done"
        assert "Test Commander" in body["result"]["favoriteCards"]

    def test_favorite_cards_fall_back_to_the_saved_deck(self):
        deck_db, _jobs = _setup()
        client = TestClient(app)
        saved = client.post(
            "/api/decks/save",
            json={"name": "Elf Deck", **LEGAL_DECK, "favoriteCards": ["Test Commander"]},
        ).json()

        start = client.post(
            "/api/analysis/dynamic",
            json={"deckId": saved["id"], "botKind": "greedy", "numMatches": 1, "maxTurns": 2},
        )
        job_id = start.json()["jobId"]

        deadline = time.time() + 10
        body = {"status": "queued"}
        while body["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.02)
            body = client.get(f"/api/analysis/dynamic/{job_id}").json()

        assert body["status"] == "done"
        assert "Test Commander" in body["result"]["favoriteCards"]

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


class TestPassiveOpponentCount:
    def test_three_independent_opponents_and_unchanged_turn_samples(self):
        from mtg_analyzer.services.game_session import build_goldfish_engine

        engine = build_goldfish_engine(_library(), with_dummy=True, dummy_count=3)
        opponents = engine.state.players[1:]
        assert [p.id for p in opponents] == ["goldfish", "goldfish-2", "goldfish-3"]
        for opponent in opponents:
            assert opponent.is_dummy
            assert len(opponent.hand) == 7
            assert all(obj.owner_id == opponent.id for obj in opponent.hand + opponent.library)
        result = run_one_match(
            _library(), None, bot=GoldfishBot("p1"), opponent_count=3, max_turns=3,
        )
        assert set(result.per_turn) == {1, 2, 3}
        assert result.per_turn[3]["card_advantage"] == 0

    def test_worker_receives_opponent_count(self, monkeypatch):
        import mtg_analyzer.services.dynamic_analysis as module

        original = module.run_one_match
        counts = []

        def observe(*args, **kwargs):
            counts.append(kwargs["opponent_count"])
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "run_one_match", observe)
        monkeypatch.setattr(module, "_match_worker_count", lambda _: 2)
        monkeypatch.setattr(module, "_run_matches_pooled", lambda libraries, payload, *args: [
            module._run_one_match_worker({**payload, "library": library}) for library in libraries
        ])
        result = run_dynamic_analysis(
            _library(), None, bot_kind="goldfish", opponent_count=3, num_matches=2, max_turns=2,
        )
        assert counts == [3, 3]
        assert result.to_dict()["opponentCount"] == 3
        assert result.matches_run == 2

    def test_api_passes_count_and_rejects_out_of_bounds(self):
        _setup()
        try:
            client = TestClient(app)
            for count in (0, 4):
                response = client.post("/api/analysis/dynamic", json={**LEGAL_DECK, "opponentCount": count})
                assert response.status_code == 422
            response = client.post("/api/analysis/dynamic", json={
                **LEGAL_DECK, "opponentCount": 3, "botKind": "goldfish", "numMatches": 1, "maxTurns": 2,
            })
            assert response.status_code == 200
            deadline = time.time() + 10
            while time.time() < deadline:
                job = client.get(f'/api/analysis/dynamic/{response.json()["jobId"]}').json()
                if job["status"] not in ("queued", "running"):
                    break
                time.sleep(0.02)
            assert job["status"] == "done"
            assert job["result"]["opponentCount"] == 3
            assert job["result"]["perTurn"][1]["mana_potential"]["n"] == 1
        finally:
            _teardown()

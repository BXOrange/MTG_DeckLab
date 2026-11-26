import sqlite3
from threading import Event
from time import monotonic, sleep

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mtg_analyzer.api import cards
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase, _BROWSE_CACHE_PREDECESSOR
from mtg_analyzer.services.schema_version import write_schema_hash


def test_browse_limits_work_and_reuses_coverage_after_restart(tmp_path, monkeypatch):
    path = tmp_path / "cards.db"
    waiting = Event()
    release = Event()
    computed = []
    marked = []

    def coverage_for(card):
        if card.name == "Beta":
            waiting.set()
            assert release.wait(5)
        computed.append(card.name)
        return {
            "modeled": card.name == "Beta",
            "source": "oracle",
            "unclaimed": [] if card.name == "Beta" else ["unknown."],
        }

    def marks(card, _unclaimed):
        marked.append(card.name)
        return {"front": {0: None}}

    monkeypatch.setattr(cards, "coverage_for", coverage_for)
    monkeypatch.setattr(cards, "_unmodeled_oracle_marks", marks)
    app = FastAPI()
    app.include_router(cards.router)
    app.dependency_overrides[cards.get_deck_database] = lambda: None

    with CardDatabase(path) as db, TestClient(app) as client:
        app.dependency_overrides[cards.get_card_database] = lambda: db
        alpha = Card(id="a", name="Alpha", type_line="Creature", is_creature=True,
                     oracle_text="Unknown.", color_identity={"U"})
        beta = Card(id="b", name="Beta", type_line="Artifact")
        db.save_cards([alpha, beta])

        try:
            first = client.get("/api/cards/browse", params={"limit": 1}).json()
            assert first["pending"]
            assert first["total"] == first["matched"] == 2
            assert first["modeled"] is None
            assert [card["name"] for card in first["cards"]] == ["Alpha"]
            assert first["cards"][0]["coverage"]["unmodeled_lines"] == {"front": [0]}
            assert waiting.wait(5)
            assert computed == ["Alpha"]
            assert marked == ["Alpha"]
            filtered = client.get("/api/cards/browse", params={"coverage": "oracle"}).json()
            assert filtered["pending"] and filtered["matched"] is None and filtered["cards"] == []
            empty = client.get("/api/cards/browse", params={"coverage": ""}).json()
            assert not empty["pending"] and empty["matched"] == empty["modeled"] == 0
        finally:
            release.set()

        deadline = monotonic() + 5
        while True:
            ready = client.get("/api/cards/browse", params={"limit": 1}).json()
            if not ready["pending"] or monotonic() > deadline:
                break
            sleep(0.01)
        assert not ready["pending"] and ready["modeled"] == 1
        assert computed == ["Alpha", "Beta"]
        assert marked == ["Alpha"]

        # Reopen the persisted verdicts while keeping the browser API and DB.
        cards.browse_cache.cache_clear()
        filtered = client.get("/api/cards/browse", params={"coverage": "oracle", "colors": "C"}).json()
        assert not filtered["pending"] and filtered["matched"] == filtered["modeled"] == 1
        assert [card["name"] for card in filtered["cards"]] == ["Beta"]
        second = client.get("/api/cards/browse", params={"limit": 1, "offset": 1}).json()
        assert [card["name"] for card in second["cards"]] == ["Beta"]
        assert computed == ["Alpha", "Beta"]

        alpha.oracle_text = "Different."
        db.save_card(alpha)
        changed = client.get("/api/cards/browse", params={"types": "creature"}).json()
        assert changed["matched"] == 1
        assert computed == ["Alpha", "Beta", "Alpha"]
        assert marked == ["Alpha", "Alpha"]


def test_browse_schema_upgrade_preserves_cached_cards(tmp_path):
    path = tmp_path / "cards.db"
    with CardDatabase(path) as db:
        db.save_card(Card(id="a", name="Alpha", type_line="Artifact"))
    with sqlite3.connect(path) as conn:
        write_schema_hash(conn, _BROWSE_CACHE_PREDECESSOR)
    with CardDatabase(path) as db:
        assert db.get_card("Alpha") is not None
        assert db.schema_migrated and not db.schema_reset

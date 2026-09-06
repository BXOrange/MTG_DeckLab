"""Tests for POST /api/decks/save, GET /api/decks, GET/DELETE /api/decks/{id}.

Reference: docs/implementation-state/Done_Backend.md "Deck persistence".
"""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.models.card import Card
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _override_database() -> DeckDatabase:
    database = DeckDatabase()
    app.dependency_overrides[get_deck_database] = lambda: database
    return database


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        return LoadCardsResult(
            cards={n: self._cards[n] for n in names if n in self._cards},
            not_found=[n for n in names if n not in self._cards],
        )


def _override_loader(cards):
    app.dependency_overrides[get_lazy_card_loader] = lambda: _FakeLoader(cards)


class _ExplodingLoader:
    """A loader that fails the test if `load_cards` is ever called — swapped
    in after the first `/validation` or `/coverage` call to prove a second
    call is served purely from the cached `Deck` field, with no re-parse/
    re-resolve at all (the actual "buffer so checks only happen if the deck
    changed" behavior, not just that the DB row ends up with something in
    it)."""

    def load_cards(self, names):
        raise AssertionError(
            "load_cards() was called again — the cached result should have "
            "made this a pure DB read with no re-resolution."
        )


def _override_loader_exploding():
    app.dependency_overrides[get_lazy_card_loader] = lambda: _ExplodingLoader()


class TestSaveDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_save_without_id_creates_a_new_deck(self):
        _override_database()
        client = TestClient(app)

        response = client.post(
            "/api/decks/save",
            json={"name": "Goblins", "commanderText": "1 Krenko, Mob Boss\n"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Goblins"
        assert body["commanderText"] == "1 Krenko, Mob Boss\n"
        assert body["id"]
        assert body["analysisId"] is None
        assert body["author"] is None

    def test_saving_twice_without_id_creates_two_decks(self):
        database = _override_database()
        client = TestClient(app)

        client.post("/api/decks/save", json={"name": "Goblins"})
        client.post("/api/decks/save", json={"name": "Goblins"})

        assert len(database.list_decks()) == 2

    def test_save_with_existing_id_updates_in_place(self):
        database = _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["id"] == created["id"]
        assert updated["name"] == "Goblins v2"
        assert updated["createdAt"] == created["createdAt"]
        assert len(database.list_decks()) == 1

    def test_update_preserves_analysis_id(self):
        database = _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()
        deck = database.get_deck(created["id"])
        deck.analysis_id = "analysis-123"
        database.save_deck(deck)

        updated = client.post(
            "/api/decks/save", json={"id": created["id"], "name": "Goblins v2"}
        ).json()

        assert updated["analysisId"] == "analysis-123"

    def test_save_with_author_persists_it(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins", "author": "Alex"}).json()

        assert created["author"] == "Alex"

    def test_update_preserves_author_when_omitted(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins", "author": "Alex"}).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["author"] == "Alex"

    def test_author_can_be_cleared(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins", "author": "Alex"}).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins", "author": ""},
        ).json()

        assert updated["author"] == ""

    def test_save_with_is_cube_persists_it(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Staples", "isCube": True}).json()

        assert created["isCube"] is True

    def test_new_deck_defaults_is_cube_to_false(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        assert created["isCube"] is False

    def test_update_preserves_is_cube_when_omitted(self):
        _override_database()
        client = TestClient(app)

        created = client.post("/api/decks/save", json={"name": "Staples", "isCube": True}).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Staples v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["isCube"] is True

    def test_save_with_archetypes_persists_them(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "archetypes": ["aristocrats", "tokens"]}
        ).json()

        assert created["archetypes"] == ["aristocrats", "tokens"]

    def test_save_with_unknown_archetype_id_drops_it(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "archetypes": ["aristocrats", "not-a-real-archetype"]}
        ).json()

        assert created["archetypes"] == ["aristocrats"]

    def test_save_with_more_than_two_archetypes_is_capped(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save",
            json={"name": "Sac Deck", "archetypes": ["aristocrats", "tokens", "stax"]},
        ).json()

        assert created["archetypes"] == ["aristocrats", "tokens"]

    def test_update_preserves_archetypes_when_omitted(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "archetypes": ["aristocrats"]}
        ).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Sac Deck v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["archetypes"] == ["aristocrats"]

    def test_update_can_explicitly_clear_archetypes(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "archetypes": ["aristocrats"]}
        ).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Sac Deck", "archetypes": []},
        ).json()

        assert updated["archetypes"] == []

    def test_save_with_favorite_cards_persists_them(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "favoriteCards": ["Blood Artist", "Sol Ring"]}
        ).json()

        assert created["favoriteCards"] == ["Blood Artist", "Sol Ring"]

    def test_update_preserves_favorite_cards_when_omitted(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "favoriteCards": ["Sol Ring"]}
        ).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Sac Deck v2", "mainboardText": "1 Sol Ring\n"},
        ).json()

        assert updated["favoriteCards"] == ["Sol Ring"]

    def test_update_can_explicitly_clear_favorite_cards(self):
        _override_database()
        client = TestClient(app)

        created = client.post(
            "/api/decks/save", json={"name": "Sac Deck", "favoriteCards": ["Sol Ring"]}
        ).json()

        updated = client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Sac Deck", "favoriteCards": []},
        ).json()

        assert updated["favoriteCards"] == []


class TestListDecks:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_empty_database_returns_empty_list(self):
        _override_database()
        client = TestClient(app)
        response = client.get("/api/decks")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_saved_decks(self):
        _override_database()
        client = TestClient(app)
        client.post("/api/decks/save", json={"name": "Goblins"})
        client.post("/api/decks/save", json={"name": "Elves"})

        response = client.get("/api/decks")

        assert response.status_code == 200
        names = {deck["name"] for deck in response.json()}
        assert names == {"Goblins", "Elves"}


class TestGetDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_get_existing_deck(self):
        _override_database()
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        response = client.get(f"/api/decks/{created['id']}")

        assert response.status_code == 200
        assert response.json()["name"] == "Goblins"

    def test_get_missing_deck_returns_404(self):
        _override_database()
        client = TestClient(app)
        response = client.get("/api/decks/nonexistent-id")
        assert response.status_code == 404


class TestDeckIdentity:
    """GET /api/decks and GET /api/decks/{id} compute + cache colorIdentity/commanders."""

    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_new_deck_has_no_computed_identity_yet(self):
        _override_database()
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()
        assert created["colorIdentity"] is None
        assert created["commanders"] is None

    def test_list_decks_computes_and_persists_identity(self):
        database = _override_database()
        _override_loader(
            {
                "Krenko, Mob Boss": Card(
                    id="Krenko", name="Krenko, Mob Boss", type_line="Legendary Creature — Goblin",
                    is_creature=True, power=2, toughness=2, color_identity={"R"},
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Goblins", "commanderText": "1 Krenko, Mob Boss\n"},
        ).json()

        response = client.get("/api/decks")

        assert response.status_code == 200
        [deck] = response.json()
        assert deck["colorIdentity"] == ["R"]
        assert deck["commanders"] == ["Krenko, Mob Boss"]
        # Persisted, not just returned — a fresh read confirms it stuck.
        assert database.get_deck(created["id"]).color_identity == ["R"]

    def test_get_deck_computes_identity_from_deck_cards_without_a_commander(self):
        _override_database()
        _override_loader(
            {
                "Llanowar Elves": Card(
                    id="Elves", name="Llanowar Elves", type_line="Creature — Elf Druid",
                    is_creature=True, power=1, toughness=1, color_identity={"G"},
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save", json={"name": "Green Stuff", "mainboardText": "1 Llanowar Elves\n"}
        ).json()

        response = client.get(f"/api/decks/{created['id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["colorIdentity"] == ["G"]
        assert body["commanders"] == []

    def test_editing_decklist_text_invalidates_cached_identity(self):
        database = _override_database()
        _override_loader(
            {
                "Krenko, Mob Boss": Card(
                    id="Krenko", name="Krenko, Mob Boss", type_line="Legendary Creature — Goblin",
                    is_creature=True, power=2, toughness=2, color_identity={"R"},
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Goblins", "commanderText": "1 Krenko, Mob Boss\n"},
        ).json()
        client.get(f"/api/decks/{created['id']}")  # populate the cache
        assert database.get_deck(created["id"]).color_identity == ["R"]

        client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins", "commanderText": "1 Sol Ring\n"},
        )

        assert database.get_deck(created["id"]).color_identity is None

    def test_resaving_unchanged_text_keeps_cached_identity(self):
        database = _override_database()
        _override_loader(
            {
                "Krenko, Mob Boss": Card(
                    id="Krenko", name="Krenko, Mob Boss", type_line="Legendary Creature — Goblin",
                    is_creature=True, power=2, toughness=2, color_identity={"R"},
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Goblins", "commanderText": "1 Krenko, Mob Boss\n"},
        ).json()
        client.get(f"/api/decks/{created['id']}")  # populate the cache

        # Re-save with the same text but a different name (e.g. a rename).
        client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Goblins v2", "commanderText": "1 Krenko, Mob Boss\n"},
        )

        assert database.get_deck(created["id"]).color_identity == ["R"]


class TestDeckValidation:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_illegal_deck_reports_not_legal(self):
        _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        # 40 cards, no commander → structurally illegal.
        created = client.post("/api/decks/save", json={"name": "Half", "mainboardText": "40 Forest\n"}).json()

        response = client.get(f"/api/decks/{created['id']}/validation")

        assert response.status_code == 200
        body = response.json()
        assert body["isLegal"] is False
        assert body["errors"]

    def test_cube_deck_skips_validation_and_reports_legal(self):
        _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        # Same structurally-illegal shape as test_illegal_deck_reports_not_legal
        # (40 cards, no commander) — but isCube should make that a non-issue.
        created = client.post(
            "/api/decks/save", json={"name": "Staples", "mainboardText": "40 Forest\n", "isCube": True}
        ).json()

        response = client.get(f"/api/decks/{created['id']}/validation")

        assert response.status_code == 200
        body = response.json()
        assert body["isLegal"] is True
        assert body["errors"] == []

    def test_legal_deck_reports_legal(self):
        _override_database()
        _override_loader(
            {
                "Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True),
                "Test Commander": Card(
                    id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
                    is_creature=True, power=1, toughness=1, color_identity=set(),
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Mono-G", "commanderText": "1 Test Commander\n", "mainboardText": "99 Forest\n"},
        ).json()

        response = client.get(f"/api/decks/{created['id']}/validation")

        assert response.status_code == 200
        assert response.json()["isLegal"] is True

    def test_validation_of_unknown_deck_is_404(self):
        _override_database()
        _override_loader({})
        client = TestClient(app)
        assert client.get("/api/decks/nope/validation").status_code == 404

    def test_second_validation_call_is_served_from_cache(self):
        # The concrete "checks only take place if a deck was changed" fix:
        # a repeat call must be a pure DB read, not another parse+resolve+
        # validate pass — proven here by swapping in a loader that fails
        # the test if it's ever invoked a second time.
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Half", "mainboardText": "40 Forest\n"}).json()

        first = client.get(f"/api/decks/{created['id']}/validation")
        assert database.get_deck(created["id"]).validation_result is not None

        _override_loader_exploding()
        second = client.get(f"/api/decks/{created['id']}/validation")

        assert second.status_code == 200
        assert second.json() == first.json()

    def test_editing_decklist_text_invalidates_cached_validation(self):
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Half", "mainboardText": "40 Forest\n"}).json()
        client.get(f"/api/decks/{created['id']}/validation")  # populate the cache
        assert database.get_deck(created["id"]).validation_result is not None

        client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Half", "mainboardText": "41 Forest\n"},
        )

        assert database.get_deck(created["id"]).validation_result is None

    def test_toggling_is_cube_invalidates_cached_validation_even_with_unchanged_text(self):
        # is_cube changes what validation *means* (RULE checks skipped
        # entirely for a cube) even though the decklist text itself didn't
        # change, so it must invalidate the cache on its own.
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Half", "mainboardText": "40 Forest\n"}).json()
        client.get(f"/api/decks/{created['id']}/validation")  # populate the cache
        assert database.get_deck(created["id"]).validation_result is not None

        client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Half", "mainboardText": "40 Forest\n", "isCube": True},
        )

        assert database.get_deck(created["id"]).validation_result is None

    def test_unresolved_card_does_not_cache_a_possibly_wrong_validation(self):
        # A card that failed to resolve means the real ban-list/color-
        # identity checks were skipped in favor of a warning — caching that
        # would freeze a possibly-wrong answer until the text next changes,
        # instead of retrying (and self-healing) on the next view.
        database = _override_database()
        _override_loader({})  # nothing resolves
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Mono-G", "commanderText": "1 Test Commander\n", "mainboardText": "99 Forest\n"},
        ).json()

        response = client.get(f"/api/decks/{created['id']}/validation")

        assert response.status_code == 200
        assert response.json()["warnings"]
        assert database.get_deck(created["id"]).validation_result is None


class TestDeckCoverage:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_fully_modeled_deck_reports_zero_unmodeled(self):
        _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Lands", "mainboardText": "40 Forest\n"}).json()

        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        body = response.json()
        assert body["unmodeledCount"] == 0
        assert body["unmodeledCardNames"] == []

    def test_unmodeled_cards_are_counted_by_quantity_and_named(self):
        _override_database()
        _override_loader(
            {
                "Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True),
                "Weird Card": Card(
                    id="Weird",
                    name="Weird Card",
                    type_line="Creature — Weird",
                    is_creature=True,
                    power=1,
                    toughness=1,
                    oracle_text="This is some totally unparseable nonsense clause that the parser will never understand.",
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Mixed", "mainboardText": "39 Forest\n1 Weird Card\n"},
        ).json()

        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        body = response.json()
        assert body["unmodeledCount"] == 1
        assert body["unmodeledCardNames"] == ["Weird Card"]

    def test_cube_deck_is_still_checked_for_coverage(self):
        _override_database()
        _override_loader(
            {
                "Weird Card": Card(
                    id="Weird",
                    name="Weird Card",
                    type_line="Creature — Weird",
                    is_creature=True,
                    power=1,
                    toughness=1,
                    oracle_text="This is some totally unparseable nonsense clause that the parser will never understand.",
                ),
            }
        )
        client = TestClient(app)
        created = client.post(
            "/api/decks/save",
            json={"name": "Staples", "mainboardText": "1 Weird Card\n", "isCube": True},
        ).json()

        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        assert response.json()["unmodeledCount"] == 1

    def test_unresolved_card_is_not_counted_as_unmodeled(self):
        _override_database()
        _override_loader({})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Unknown", "mainboardText": "1 Nonexistent Card\n"}).json()

        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        assert response.json()["unmodeledCount"] == 0

    def test_coverage_of_unknown_deck_is_404(self):
        _override_database()
        _override_loader({})
        client = TestClient(app)
        assert client.get("/api/decks/nope/coverage").status_code == 404

    def test_second_coverage_call_is_served_from_cache(self):
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Lands", "mainboardText": "40 Forest\n"}).json()

        first = client.get(f"/api/decks/{created['id']}/coverage")
        assert database.get_deck(created["id"]).unmodeled_coverage is not None
        assert database.get_deck(created["id"]).unmodeled_coverage_version is not None

        _override_loader_exploding()
        second = client.get(f"/api/decks/{created['id']}/coverage")

        assert second.status_code == 200
        assert second.json() == first.json()

    def test_parser_version_change_recalculates_cached_coverage(self, monkeypatch):
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Lands", "mainboardText": "40 Forest\n"}).json()
        client.get(f"/api/decks/{created['id']}/coverage")

        deck = database.get_deck(created["id"])
        deck.unmodeled_coverage = {"unmodeledCount": 40, "unmodeledCardNames": ["Forest"]}
        deck.unmodeled_coverage_version = "obsolete"
        database.save_deck(deck)

        monkeypatch.setattr("mtg_analyzer.api.saved_decks.PARSER_VERSION", "next-version")
        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        assert response.json() == {"unmodeledCount": 0, "unmodeledCardNames": []}
        assert database.get_deck(created["id"]).unmodeled_coverage_version == "next-version"

    def test_editing_decklist_text_invalidates_cached_coverage(self):
        database = _override_database()
        _override_loader({"Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)})
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Lands", "mainboardText": "40 Forest\n"}).json()
        client.get(f"/api/decks/{created['id']}/coverage")  # populate the cache
        assert database.get_deck(created["id"]).unmodeled_coverage is not None

        client.post(
            "/api/decks/save",
            json={"id": created["id"], "name": "Lands", "mainboardText": "41 Forest\n"},
        )

        assert database.get_deck(created["id"]).unmodeled_coverage is None

    def test_unresolved_card_does_not_cache_a_possible_undercount(self):
        # A card that fails to resolve is silently excluded from the count
        # rather than counted as unmodeled — caching that would freeze a
        # possible undercount instead of retrying on the next view.
        database = _override_database()
        _override_loader({})
        client = TestClient(app)
        created = client.post(
            "/api/decks/save", json={"name": "Unknown", "mainboardText": "1 Nonexistent Card\n"}
        ).json()

        response = client.get(f"/api/decks/{created['id']}/coverage")

        assert response.status_code == 200
        assert database.get_deck(created["id"]).unmodeled_coverage is None


class TestDeleteDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_deck_database, None)

    def test_delete_existing_deck(self):
        database = _override_database()
        client = TestClient(app)
        created = client.post("/api/decks/save", json={"name": "Goblins"}).json()

        response = client.delete(f"/api/decks/{created['id']}")

        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        assert database.get_deck(created["id"]) is None

    def test_delete_missing_deck_returns_404(self):
        _override_database()
        client = TestClient(app)
        response = client.delete("/api/decks/nonexistent-id")
        assert response.status_code == 404

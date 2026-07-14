"""Tests for the HTTP API (POST /api/decks, GET /api/health).

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation".
"""

import httpx2 as httpx
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.decks import get_lazy_card_loader
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration

client = TestClient(app)

SAMPLE_MAINBOARD = "\n".join(f"1 Goblin {i}" for i in range(37)) + "\n62 Mountain\n"

KRENKO = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Krenko, Mob Boss",
    "mana_cost": "{2}{R}{R}",
    "cmc": 4.0,
    "type_line": "Legendary Creature — Goblin",
    "oracle_text": "",
    "power": "3",
    "toughness": "3",
    "colors": ["R"],
    "color_identity": ["R"],
    "keywords": [],
    "set": "cma",
    "rarity": "rare",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

CULTIVATE = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Cultivate",
    "mana_cost": "{2}{G}",
    "cmc": 3.0,
    "type_line": "Sorcery",
    "oracle_text": "Search your library for up to two basic land cards...",
    "colors": ["G"],
    "color_identity": ["G"],
    "keywords": [],
    "set": "cma",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

SHEOLDRED = {
    "id": "33333333-3333-3333-3333-333333333333",
    "name": "Sheoldred, the Apocalypse",
    "mana_cost": "{2}{B}{B}",
    "cmc": 4.0,
    "type_line": "Legendary Creature — Phyrexian Praetor",
    "oracle_text": "",
    "power": "4",
    "toughness": "5",
    "colors": ["B"],
    "color_identity": ["B"],
    "keywords": [],
    "set": "dmu",
    "rarity": "mythic",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

# "Partner with X" reciprocal pair, shaped after the real Scryfall data for
# Frodo, Adventurous Hobbit // Sam, Loyal Attendant (LTR) — one face's
# "Partner with" line carries its RULE 207.2 reminder text inline, which
# must be stripped before matching the other card's exact name (see
# scryfall_client._partner_with).
FRODO = {
    "id": "44444444-4444-4444-4444-444444444444",
    "name": "Frodo, Adventurous Hobbit",
    "mana_cost": "{1}{W}",
    "cmc": 2.0,
    "type_line": "Legendary Creature — Hobbit",
    "oracle_text": "Partner with Sam, Loyal Attendant\nVigilance",
    "power": "1",
    "toughness": "1",
    "colors": ["W"],
    "color_identity": ["W"],
    "keywords": ["Partner with", "Vigilance"],
    "set": "ltr",
    "rarity": "rare",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

SAM = {
    "id": "55555555-5555-5555-5555-555555555555",
    "name": "Sam, Loyal Attendant",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "type_line": "Legendary Creature — Hobbit",
    "oracle_text": (
        "Partner with Frodo, Adventurous Hobbit (When this creature enters, "
        "target player may put Frodo into their hand from their library, "
        "then shuffle.)\nAt the beginning of combat on your turn, create a Food token."
    ),
    "power": "1",
    "toughness": "1",
    "colors": ["G"],
    "color_identity": ["G"],
    "keywords": ["Partner with"],
    "set": "ltr",
    "rarity": "rare",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

# Modal double-faced card: no top-level mana_cost/oracle_text (only
# per-face), but color_identity is already the Scryfall-computed union
# of both faces — Valki alone is mono-black, Tibalt alone is black-red.
# Real data (trimmed): https://api.scryfall.com/cards/named?exact=Valki,+God+of+Lies
VALKI_TIBALT = {
    "id": "44444444-4444-4444-4444-444444444444",
    "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
    "layout": "modal_dfc",
    "cmc": 2.0,
    "type_line": "Legendary Creature — God // Legendary Planeswalker — Tibalt",
    "color_identity": ["B", "R"],
    "keywords": [],
    "set": "khm",
    "rarity": "mythic",
    "card_faces": [
        {
            "object": "card_face",
            "name": "Valki, God of Lies",
            "mana_cost": "{1}{B}",
            "type_line": "Legendary Creature — God",
            "oracle_text": "",
            "colors": ["B"],
            "power": "2",
            "toughness": "1",
            "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
        },
        {
            "object": "card_face",
            "name": "Tibalt, Cosmic Impostor",
            "mana_cost": "{5}{B}{R}",
            "type_line": "Legendary Planeswalker — Tibalt",
            "oracle_text": "",
            "colors": ["B", "R"],
            "loyalty": "5",
            "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
        },
    ],
}


def _not_found_handler(request: httpx.Request) -> httpx.Response:
    import json

    if request.url.path == "/cards/collection":
        identifiers = json.loads(request.read())["identifiers"]
        return httpx.Response(
            200,
            json={"data": [], "not_found": [{"name": i["name"]} for i in identifiers]},
        )
    # The flavor-name fallback retry (see LazyCardLoader.load_cards) hits
    # /cards/named for each collection miss — genuinely unknown here too.
    return httpx.Response(404, json={"details": "not found"})


def _override_loader(handler):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(
        client=httpx.Client(transport=transport, base_url="https://api.scryfall.com")
    )
    loader = LazyCardLoader(database, scryfall)
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    return loader


class TestHealth:
    def test_health_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSubmitDeck:
    def teardown_method(self):
        app.dependency_overrides.pop(get_lazy_card_loader, None)

    def test_legal_deck_round_trip(self):
        _override_loader(_not_found_handler)
        response = client.post(
            "/api/decks",
            json={
                "commanderText": "1 Krenko, Mob Boss",
                "mainboardText": SAMPLE_MAINBOARD,
                "sideboardText": "",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["totalCount"] == 100
        assert body["validation"]["isLegal"] is True
        assert body["commanders"] == [{"name": "Krenko, Mob Boss", "qty": 1}]

    def test_illegal_deck_reports_errors(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={"mainboardText": "1 Sol Ring"})
        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert body["validation"]["errors"]

    def test_missing_fields_default_to_empty(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["totalCount"] == 0
        assert body["validation"]["warnings"]

    def test_snake_case_field_names_also_accepted(self):
        _override_loader(_not_found_handler)
        response = client.post("/api/decks", json={"mainboard_text": "1 Sol Ring"})
        assert response.status_code == 200
        assert response.json()["totalCount"] == 1

    def test_card_outside_commander_color_identity_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [KRENKO, CULTIVATE], "not_found": []})

        _override_loader(handler)
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Krenko, Mob Boss", "mainboardText": "1 Cultivate"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert any("Cultivate" in error for error in body["validation"]["errors"])
        assert body["validation"]["colorIdentityViolationNames"] == ["Cultivate"]
        assert body["validation"]["bannedCardNames"] == []

    def test_banned_card_is_reported_by_name(self):
        black_lotus = {
            "id": "99999999-9999-9999-9999-999999999999",
            "name": "Black Lotus",
            "mana_cost": "{0}",
            "cmc": 0.0,
            "type_line": "Artifact",
            "oracle_text": "",
            "colors": [],
            "color_identity": [],
            "keywords": [],
            "set": "lea",
            "rarity": "rare",
            "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [KRENKO, black_lotus], "not_found": []})

        _override_loader(handler)
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Krenko, Mob Boss", "mainboardText": "1 Black Lotus"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert body["validation"]["bannedCardNames"] == ["Black Lotus"]
        assert body["validation"]["colorIdentityViolationNames"] == []

    def test_mdfc_back_face_color_outside_identity_is_reported(self):
        # Valki (front face) is mono-black, matching the commander — but
        # the card's true color identity also includes Tibalt's red
        # back face. A bug that only looked at the front face would
        # miss this; the real (Scryfall-computed) color_identity catches it.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [SHEOLDRED, VALKI_TIBALT], "not_found": []})

        _override_loader(handler)
        response = client.post(
            "/api/decks",
            json={
                "commanderText": "1 Sheoldred, the Apocalypse",
                "mainboardText": "1 Valki, God of Lies",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is False
        assert any("Tibalt" in error or "Valki" in error for error in body["validation"]["errors"])
        assert body["validation"]["colorIdentityViolationNames"] == [
            "Valki, God of Lies // Tibalt, Cosmic Impostor"
        ]

    def test_mdfc_within_commander_identity_is_legal(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Commander's own identity already covers black+red, so the
            # MDFC's full (front+back) identity fits inside it.
            rakdos_commander = {**SHEOLDRED, "color_identity": ["B", "R"]}
            return httpx.Response(200, json={"data": [rakdos_commander, VALKI_TIBALT], "not_found": []})

        _override_loader(handler)
        mainboard = "1 Valki, God of Lies\n" + "\n".join(f"1 Filler {i}" for i in range(98)) + "\n"
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Sheoldred, the Apocalypse", "mainboardText": mainboard},
        )

        assert response.status_code == 200
        assert response.json()["totalCount"] == 100
        assert response.json()["validation"]["isLegal"] is True

    def test_reciprocal_partner_with_pair_is_legal_despite_inline_reminder_text(self):
        # Regression test: Frodo, Adventurous Hobbit // Sam, Loyal
        # Attendant were wrongly rejected as an illegal commander pair
        # because Sam's real oracle text has its "Partner with" reminder
        # text inline, which a naive capture doesn't strip before
        # comparing names (see scryfall_client._partner_with).
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [FRODO, SAM], "not_found": []})

        _override_loader(handler)
        mainboard = "\n".join(f"1 Filler {i}" for i in range(98)) + "\n"
        response = client.post(
            "/api/decks",
            json={
                "commanderText": "1 Frodo, Adventurous Hobbit\n1 Sam, Loyal Attendant",
                "mainboardText": mainboard,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["validation"]["isLegal"] is True
        assert body["validation"]["errors"] == []

    def test_unresolved_cards_add_a_warning_but_no_error(self):
        _override_loader(_not_found_handler)
        response = client.post(
            "/api/decks",
            json={"commanderText": "1 Not A Real Commander", "mainboardText": "1 Sol Ring"},
        )

        assert response.status_code == 200
        body = response.json()
        assert any("Not A Real Commander" in warning for warning in body["validation"]["warnings"])

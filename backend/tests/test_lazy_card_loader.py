"""Tests for LazyCardLoader: DB-first lookup, Scryfall fallback for misses.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "LazyCardLoader").
"""

import httpx2 as httpx

from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration

LIGHTNING_BOLT = {
    "id": "77c17415-56c9-4677-b6d5-e18641640e6f",
    "name": "Lightning Bolt",
    "mana_cost": "{R}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "colors": ["R"],
    "color_identity": ["R"],
    "keywords": [],
    "set": "clu",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}


def make_loader(handler):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
    return LazyCardLoader(database, scryfall), database


class TestLoadCards:
    def test_fetches_from_scryfall_on_first_use(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, database = make_loader(handler)
        result = loader.load_cards(["Lightning Bolt"])

        assert result.cards["Lightning Bolt"].name == "Lightning Bolt"
        assert result.not_found == []
        assert len(calls) == 1
        # Second load must hit the DB, not Scryfall again.
        assert database.get_card("Lightning Bolt") is not None

    def test_second_load_does_not_call_scryfall_again(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        loader.load_cards(["Lightning Bolt"])
        loader.load_cards(["Lightning Bolt"])

        assert len(calls) == 1

    def test_unknown_card_reported_as_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [], "not_found": [{"name": "Not A Real Card"}]}
            )

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Not A Real Card"])

        assert result.cards == {}
        assert result.not_found == ["Not A Real Card"]

    def test_lookup_is_case_insensitive_to_requested_name(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        result = loader.load_cards(["lightning bolt"])

        assert "lightning bolt" in result.cards
        assert result.cards["lightning bolt"].name == "Lightning Bolt"

    def test_duplicate_names_deduped_before_fetch(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            body = request.read()
            import json

            identifiers = json.loads(body)["identifiers"]
            assert len(identifiers) == 1
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        loader.load_cards(["Lightning Bolt", "Lightning Bolt"])

        assert len(calls) == 1

    def test_mixed_cached_and_missing_only_fetches_missing(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            import json

            identifiers = json.loads(request.read())["identifiers"]
            assert identifiers == [{"name": "Lightning Bolt"}]
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        database = CardDatabase()
        transport = httpx.MockTransport(handler)
        scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
        loader = LazyCardLoader(database, scryfall)

        # Pre-seed "Counterspell" directly so only "Lightning Bolt" is missing.
        from mtg_analyzer.models.card import Card

        database.save_card(
            Card(
                id="counterspell-id",
                name="Counterspell",
                type_line="Instant",
                is_instant=True,
            )
        )

        result = loader.load_cards(["Counterspell", "Lightning Bolt"])

        assert set(result.cards) == {"Counterspell", "Lightning Bolt"}
        assert len(calls) == 1

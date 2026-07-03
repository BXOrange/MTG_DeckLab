"""Tests for Scryfall response parsing and the ScryfallIntegration client.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3).
"""

import httpx2 as httpx
import pytest

from mtg_analyzer.services.scryfall_client import (
    ScryfallIntegration,
    ScryfallNotFoundError,
    card_from_scryfall_data,
)

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
    "image_uris": {
        "small": "https://cards.scryfall.io/small/lightning_bolt.jpg",
        "normal": "https://cards.scryfall.io/normal/lightning_bolt.jpg",
        "large": "https://cards.scryfall.io/large/lightning_bolt.jpg",
        "png": "https://cards.scryfall.io/png/lightning_bolt.png",
    },
}

GRIZZLY_BEARS = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Grizzly Bears",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "type_line": "Creature — Bear",
    "oracle_text": "",
    "colors": ["G"],
    "color_identity": ["G"],
    "keywords": [],
    "power": "2",
    "toughness": "2",
    "set": "a25",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

THRASIOS = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Thrasios, Triton Hero",
    "mana_cost": "{G}{U}",
    "cmc": 2.0,
    "type_line": "Legendary Creature — Merfolk Wizard",
    "oracle_text": (
        "Partner (You can have two commanders if both have partner.)\n"
        "{1}{G/U}, {T}: Scry X, where X is the number of cards you've drawn this turn."
    ),
    "colors": ["G", "U"],
    "color_identity": ["G", "U"],
    "keywords": ["Partner"],
    "power": "1",
    "toughness": "3",
    "set": "cma",
    "rarity": "mythic",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}


class TestCardFromScryfallData:
    def test_instant(self):
        card = card_from_scryfall_data(LIGHTNING_BOLT)
        assert card.name == "Lightning Bolt"
        assert card.is_instant is True
        assert card.mana_cost["R"] == 1
        assert card.converted_mana_cost == 1
        assert card.color_identity == {"R"}
        assert card.image_uri_normal == LIGHTNING_BOLT["image_uris"]["normal"]
        assert card.set_code == "clu"
        assert card.rarity == "common"

    def test_creature_power_toughness_parsed_as_int(self):
        card = card_from_scryfall_data(GRIZZLY_BEARS)
        assert card.is_creature is True
        assert card.power == 2
        assert card.toughness == 2
        # Generic mana ("{1}") isn't representable per-color; only the pip is kept.
        assert card.mana_cost["G"] == 1

    def test_non_creature_has_no_power_toughness(self):
        card = card_from_scryfall_data(LIGHTNING_BOLT)
        assert card.power is None
        assert card.toughness is None

    def test_partner_card_detected(self):
        card = card_from_scryfall_data(THRASIOS)
        assert card.has_partner is True
        assert card.partner_with is None
        assert card.is_legendary is True

    def test_partner_with_named_card(self):
        data = {
            **THRASIOS,
            "id": "33333333-3333-3333-3333-333333333333",
            "name": "Ravos, Dux of Bricktown",
            "oracle_text": "Partner with Silas Renn, Seeker Adept",
        }
        card = card_from_scryfall_data(data)
        assert card.has_partner is True
        assert card.partner_with == "Silas Renn, Seeker Adept"

    def test_variable_power_toughness_is_none(self):
        data = {**GRIZZLY_BEARS, "power": "*", "toughness": "*"}
        card = card_from_scryfall_data(data)
        assert card.power is None
        assert card.toughness is None


class TestScryfallIntegration:
    def _client(self, handler) -> ScryfallIntegration:
        transport = httpx.MockTransport(handler)
        return ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))

    def test_fetch_card_returns_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["exact"] == "Lightning Bolt"
            return httpx.Response(200, json=LIGHTNING_BOLT)

        with self._client(handler) as scryfall:
            data = scryfall.fetch_card("Lightning Bolt")
        assert data["name"] == "Lightning Bolt"

    def test_fetch_card_not_found_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"details": "not found"})

        with self._client(handler) as scryfall:
            with pytest.raises(ScryfallNotFoundError):
                scryfall.fetch_card("Not A Real Card")

    def test_fetch_multiple_splits_found_and_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [LIGHTNING_BOLT],
                    "not_found": [{"name": "Not A Real Card"}],
                },
            )

        with self._client(handler) as scryfall:
            found, not_found = scryfall.fetch_multiple(["Lightning Bolt", "Not A Real Card"])
        assert [c["name"] for c in found] == ["Lightning Bolt"]
        assert not_found == ["Not A Real Card"]

    def test_fetch_multiple_batches_over_75_identifiers(self):
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json={"data": [], "not_found": []})

        names = [f"Card {i}" for i in range(150)]
        with self._client(handler) as scryfall:
            scryfall.fetch_multiple(names)
        assert request_count == 2

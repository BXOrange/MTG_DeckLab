"""Tests for the repo-committed token catalogue + token image lazy-loading.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (three-tier durability model:
the token catalogue ships in the repo; images stay lazy-loaded).
"""

import json

import httpx2 as httpx
import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.image_cache import ImageCache
from mtg_analyzer.services.token_database import DEFAULT_TOKENS_PATH, TokenDatabase


class TestSeededCatalogue:
    def test_loads_the_five_seeded_tokens(self):
        db = TokenDatabase()
        names = {c.name for c in db.all_tokens()}
        assert {"Treasure", "Clue", "Food", "Soldier", "Zombie"} <= names
        assert len(db) == len(db.all_tokens())

    def test_lookup_by_name_is_case_insensitive(self):
        db = TokenDatabase()
        assert db.get_token("treasure") is db.get_token("Treasure")
        assert db.get_token("Treasure").name == "Treasure"

    def test_lookup_by_id(self):
        db = TokenDatabase()
        treasure = db.get_token("Treasure")
        assert db.get_token_by_id(treasure.id) is treasure

    def test_missing_token_is_none(self):
        db = TokenDatabase()
        assert db.get_token("Not A Real Token") is None
        assert db.get_token_by_id("00000000-0000-0000-0000-000000000000") is None

    def test_treasure_carries_its_activated_ability_text(self):
        # The whole point: a token's oracle text is real, so the parser can
        # derive its "{T}, Sacrifice ...: Add one mana" activated ability.
        treasure = TokenDatabase().get_token("Treasure")
        assert "Add one mana of any color" in treasure.oracle_text
        assert treasure.is_token

    def test_creature_tokens_have_power_toughness(self):
        db = TokenDatabase()
        soldier, zombie = db.get_token("Soldier"), db.get_token("Zombie")
        assert (soldier.power, soldier.toughness) == (1, 1)
        assert (zombie.power, zombie.toughness) == (2, 2)
        assert soldier.is_creature and zombie.is_creature


class TestCatalogueIntegrity:
    def test_every_entry_is_a_token(self):
        # Guards the invariant TokenDatabase enforces on load.
        for entry in json.loads(DEFAULT_TOKENS_PATH.read_text(encoding="utf-8")):
            assert Card.from_dict(entry).is_token

    def test_rejects_a_non_token_entry(self, tmp_path):
        real_card = Card(id="x", name="Grizzly Bears", type_line="Creature — Bear")
        bad = tmp_path / "tokens.json"
        bad.write_text(json.dumps([real_card.to_dict()]))
        with pytest.raises(ValueError, match="not a token"):
            TokenDatabase(tokens_path=bad)


class TestTokenImageLazyLoading:
    """Token art reuses the id-keyed ImageCache with no new code."""

    def test_token_image_downloads_once_then_serves_from_disk(self, tmp_path):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, content=b"token-art-bytes")

        client = httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://cards.scryfall.io"
        )
        cache = ImageCache(cache_dir=tmp_path / "images", client=client)

        treasure = TokenDatabase().get_token("Treasure")
        first = cache.get_or_fetch(treasure.id, "normal", treasure.image_uri_normal)
        second = cache.get_or_fetch(treasure.id, "normal", treasure.image_uri_normal)

        assert first == second and first.exists()
        assert first.read_bytes() == b"token-art-bytes"
        assert len(calls) == 1  # lazy: fetched only on first use, then cached

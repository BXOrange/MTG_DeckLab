"""Tests for the repo-committed token catalogue + token image lazy-loading.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (three-tier durability model:
the token catalogue ships in the repo; images stay lazy-loaded).
"""

import json

import httpx2 as httpx
import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.image_cache import ImageCache
from mtg_analyzer.services.token_database import (
    DEFAULT_TOKENS_PATH,
    TokenArtLibrary,
    TokenDatabase,
    synthesize_token_card,
)


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


class TestTokenArtLibrary:
    """The art-only library `synthesize_token_card` uses for ad hoc tokens.

    Reference: `scripts/build_token_art_library.py` (how `data/token_art.json`
    is built from Scryfall's token sheets).
    """

    def test_common_vanilla_token_resolves_real_art(self):
        # "1/1 white Soldier" is one of the most-reprinted tokens in Magic —
        # if the library doesn't cover this, it doesn't cover anything.
        soldier = synthesize_token_card("Soldier", power=1, toughness=1, colors=["W"])
        assert soldier.image_uri_small
        assert soldier.id != "token:Soldier:1/1"  # got a real Scryfall id, not the placeholder

    def test_different_stat_variants_of_the_same_name_get_different_art(self):
        # The whole point of keying by (name, power, toughness, colors)
        # rather than name alone: Magic reprints "Shapeshifter" tokens at
        # several different stat lines, and each must show its own art.
        small = synthesize_token_card("Shapeshifter", power=1, toughness=1, colors=[])
        big = synthesize_token_card("Shapeshifter", power=2, toughness=2, colors=["U"])
        assert small.image_uri_small and big.image_uri_small
        assert small.id != big.id
        assert small.image_uri_small != big.image_uri_small

    def test_unmatched_token_keeps_the_old_imageless_placeholder(self):
        # No card has ever printed a "9/9 pink Zzznotarealtoken" — a miss
        # must leave `synthesize_token_card`'s pre-existing behaviour alone.
        token = synthesize_token_card("Zzznotarealtoken", power=9, toughness=9, colors=[])
        assert not token.image_uri_small
        assert token.id == "token:Zzznotarealtoken:9/9"

    def test_find_ignores_color_order(self):
        library = TokenArtLibrary()
        entry = library.find("Soldier", 1, 1, ["W"])
        assert entry is not None
        assert entry["name"] == "Soldier"

    def test_find_returns_none_for_unknown_combo(self):
        library = TokenArtLibrary()
        assert library.find("Soldier", 999, 999, ["W"]) is None
        assert library.find(None, 1, 1, ["W"]) is None

    def test_missing_file_yields_an_empty_library(self, tmp_path):
        library = TokenArtLibrary(path=tmp_path / "does_not_exist.json")
        assert library.find("Soldier", 1, 1, ["W"]) is None


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

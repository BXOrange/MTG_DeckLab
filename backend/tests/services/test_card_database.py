"""Tests for the SQLite-backed CardDatabase.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3).
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase


def make_card(**overrides) -> Card:
    defaults = dict(
        id="11111111-1111-1111-1111-111111111111",
        name="Lightning Bolt",
        type_line="Instant",
        mana_cost={"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0},
        converted_mana_cost=1,
        color_identity={"R"},
        is_instant=True,
        oracle_text="Lightning Bolt deals 3 damage to any target.",
    )
    defaults.update(overrides)
    return Card(**defaults)


class TestSaveAndGet:
    def test_get_card_by_exact_name(self):
        db = CardDatabase()
        db.save_card(make_card())
        card = db.get_card("Lightning Bolt")
        assert card is not None
        assert card.name == "Lightning Bolt"
        assert card.oracle_text == "Lightning Bolt deals 3 damage to any target."

    def test_get_card_is_case_insensitive(self):
        db = CardDatabase()
        db.save_card(make_card())
        assert db.get_card("lightning bolt") is not None
        assert db.get_card("LIGHTNING BOLT") is not None

    def test_get_missing_card_returns_none(self):
        db = CardDatabase()
        assert db.get_card("Nonexistent Card") is None

    def test_get_card_by_front_face_name_of_a_multi_faced_card(self):
        db = CardDatabase()
        db.save_card(make_card(name="Valki, God of Lies // Tibalt, Cosmic Impostor"))
        card = db.get_card("Valki, God of Lies")
        assert card is not None
        assert card.name == "Valki, God of Lies // Tibalt, Cosmic Impostor"

    def test_get_card_by_front_face_name_is_case_insensitive(self):
        db = CardDatabase()
        db.save_card(make_card(name="Valki, God of Lies // Tibalt, Cosmic Impostor"))
        assert db.get_card("valki, god of lies") is not None

    def test_get_card_does_not_match_unrelated_prefix(self):
        db = CardDatabase()
        db.save_card(make_card(name="Valki, God of Lies // Tibalt, Cosmic Impostor"))
        assert db.get_card("Valki") is None

    def test_get_card_by_single_slash_full_name(self):
        # Decklists sometimes write the separator as a single slash — the
        # cache should still match the stored "Front // Back" row.
        db = CardDatabase()
        db.save_card(make_card(name="Valki, God of Lies // Tibalt, Cosmic Impostor"))
        card = db.get_card("Valki, God of Lies / Tibalt, Cosmic Impostor")
        assert card is not None
        assert card.name == "Valki, God of Lies // Tibalt, Cosmic Impostor"

    def test_get_card_by_flavor_name(self):
        # Secret Lair's "Godzilla" series (Ikoria) prints an alternate
        # name alongside the real one — Card.flavor_name.
        db = CardDatabase()
        db.save_card(make_card(name="Zilortha, Strength Incarnate", flavor_name="Godzilla, King of the Monsters"))
        card = db.get_card("Godzilla, King of the Monsters")
        assert card is not None
        assert card.name == "Zilortha, Strength Incarnate"

    def test_get_card_by_flavor_name_is_case_insensitive(self):
        db = CardDatabase()
        db.save_card(make_card(name="Zilortha, Strength Incarnate", flavor_name="Godzilla, King of the Monsters"))
        assert db.get_card("godzilla, king of the monsters") is not None

    def test_blank_flavor_name_does_not_match_other_blank_lookups(self):
        # Most rows have no flavor_name at all — an empty-string lookup
        # (which should never happen from a real decklist name, but
        # guards the column default) must not accidentally match them.
        db = CardDatabase()
        db.save_card(make_card())
        assert db.get_card("") is None

    def test_get_card_by_id(self):
        db = CardDatabase()
        db.save_card(make_card())
        card = db.get_card_by_id("11111111-1111-1111-1111-111111111111")
        assert card is not None
        assert card.name == "Lightning Bolt"

    def test_save_card_round_trips_all_fields(self):
        db = CardDatabase()
        original = make_card(keywords=["Flash"], set_code="lea", rarity="common", flavor_name="Fireball, Basically")
        db.save_card(original)
        restored = db.get_card("Lightning Bolt")
        assert restored == original


class TestUpsert:
    def test_save_card_twice_updates_in_place(self):
        db = CardDatabase()
        db.save_card(make_card(oracle_text="old text"))
        db.save_card(make_card(oracle_text="new text"))
        card = db.get_card("Lightning Bolt")
        assert card.oracle_text == "new text"

    def test_save_card_renamed_updates_name_lookup(self):
        db = CardDatabase()
        db.save_card(make_card(name="Old Name"))
        db.save_card(make_card(name="New Name"))
        assert db.get_card("Old Name") is None
        assert db.get_card("New Name") is not None

    def test_different_printing_with_same_name_replaces_rather_than_errors(self):
        # Two different Scryfall ids (different printings) can resolve to
        # the same Oracle `name` — e.g. a plain "Nyxbloom Ancient" cached
        # first, then a Final Fantasy crossover printing later resolved by
        # its flavor name "The Cloudsea Djinn" (LazyCardLoader's
        # /cards/named fallback). A naive `ON CONFLICT(id)` upsert doesn't
        # catch this (different id) and would violate the UNIQUE `name`
        # index instead — regression test for that IntegrityError.
        db = CardDatabase()
        db.save_card(make_card(id="11111111-1111-1111-1111-111111111111", name="Nyxbloom Ancient"))
        db.save_card(
            make_card(
                id="22222222-2222-2222-2222-222222222222",
                name="Nyxbloom Ancient",
                flavor_name="The Cloudsea Djinn",
            )
        )
        card = db.get_card("Nyxbloom Ancient")
        assert card is not None
        assert card.id == "22222222-2222-2222-2222-222222222222"
        assert card.flavor_name == "The Cloudsea Djinn"
        # The old row is gone, not left behind as an orphaned duplicate.
        assert db.get_card_by_id("11111111-1111-1111-1111-111111111111") is None


class TestListCards:
    def test_lists_all_cards_ordered_by_name(self):
        db = CardDatabase()
        db.save_card(make_card(id="22222222-2222-2222-2222-222222222222", name="Counterspell"))
        db.save_card(make_card(id="11111111-1111-1111-1111-111111111111", name="Lightning Bolt"))
        assert [c.name for c in db.list_cards()] == ["Counterspell", "Lightning Bolt"]

    def test_empty_database_returns_empty_list(self):
        db = CardDatabase()
        assert db.list_cards() == []


class TestSearch:
    def test_search_matches_substring(self):
        db = CardDatabase()
        db.save_card(make_card())
        db.save_card(make_card(id="22222222-2222-2222-2222-222222222222", name="Counterspell"))
        results = db.search_cards("bolt")
        assert [c.name for c in results] == ["Lightning Bolt"]

    def test_search_respects_limit(self):
        db = CardDatabase()
        for i in range(5):
            db.save_card(make_card(id=f"card-{i}", name=f"Bolt {i}"))
        results = db.search_cards("Bolt", limit=2)
        assert len(results) == 2

    def test_search_no_match_returns_empty_list(self):
        db = CardDatabase()
        db.save_card(make_card())
        assert db.search_cards("nonexistent") == []

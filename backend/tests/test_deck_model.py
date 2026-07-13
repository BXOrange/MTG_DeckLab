"""Tests for the Deck model.

Reference: docs/implementation-state/Done_Backend.md "Deck persistence".
"""

import uuid

from mtg_analyzer.models.deck import Deck


class TestIdentity:
    def test_id_defaults_to_a_uuid(self):
        deck = Deck()
        assert uuid.UUID(deck.id)  # raises ValueError if not a valid UUID

    def test_two_decks_get_different_ids(self):
        assert Deck().id != Deck().id

    def test_explicit_id_is_kept(self):
        deck = Deck(id="my-custom-id")
        assert deck.id == "my-custom-id"

    def test_name_is_not_required_to_be_unique_or_present(self):
        deck = Deck()
        assert deck.name == ""

    def test_two_decks_may_share_a_name(self):
        a = Deck(name="Goblins")
        b = Deck(name="Goblins")
        assert a.name == b.name
        assert a.id != b.id


class TestTimestamps:
    def test_created_at_defaults_to_now(self):
        deck = Deck()
        assert deck.created_at  # non-empty ISO string

    def test_explicit_created_at_is_kept(self):
        deck = Deck(created_at="2024-01-01T00:00:00+00:00")
        assert deck.created_at == "2024-01-01T00:00:00+00:00"


class TestAnalysisHook:
    def test_analysis_id_defaults_to_none(self):
        assert Deck().analysis_id is None

    def test_analysis_id_can_be_set(self):
        deck = Deck(analysis_id="analysis-123")
        assert deck.analysis_id == "analysis-123"


class TestCachedIdentity:
    def test_color_identity_and_commanders_default_to_none(self):
        deck = Deck()
        assert deck.color_identity is None
        assert deck.commanders is None

    def test_color_identity_and_commanders_can_be_set(self):
        deck = Deck(color_identity=["B", "R"], commanders=["Krenko, Mob Boss"])
        assert deck.color_identity == ["B", "R"]
        assert deck.commanders == ["Krenko, Mob Boss"]

    def test_empty_list_round_trips_distinct_from_none(self):
        deck = Deck(color_identity=[], commanders=[])
        restored = Deck.from_dict(deck.to_dict())
        assert restored.color_identity == []
        assert restored.commanders == []


class TestSerialization:
    def test_to_dict_round_trip(self):
        deck = Deck(
            name="Krenko Goblins",
            commander_text="1 Krenko, Mob Boss\n",
            mainboard_text="1 Sol Ring\n",
            sideboard_text="1 Negate\n",
            analysis_id="analysis-1",
        )
        restored = Deck.from_dict(deck.to_dict())
        assert restored == deck

    def test_to_dict_uses_camel_case_keys(self):
        data = Deck(commander_text="x", mainboard_text="y", sideboard_text="z").to_dict()
        assert set(data) == {
            "id",
            "name",
            "commanderText",
            "mainboardText",
            "sideboardText",
            "createdAt",
            "analysisId",
            "sleeveId",
            "colorIdentity",
            "commanders",
        }

    def test_from_dict_missing_optional_fields_uses_defaults(self):
        deck = Deck.from_dict({})
        assert deck.name == ""
        assert deck.commander_text == ""
        assert deck.analysis_id is None
        assert uuid.UUID(deck.id)


class TestDunderMethods:
    def test_repr_contains_id_and_name(self):
        deck = Deck(id="abc-123", name="Goblins")
        assert "abc-123" in repr(deck)
        assert "Goblins" in repr(deck)

    def test_eq_same_data(self):
        assert Deck(id="x", created_at="t") == Deck(id="x", created_at="t")

    def test_eq_different_id(self):
        assert Deck(id="x", created_at="t") != Deck(id="y", created_at="t")

    def test_eq_against_non_deck(self):
        assert Deck() != "not a deck"

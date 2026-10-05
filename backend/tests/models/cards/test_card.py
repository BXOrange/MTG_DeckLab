"""Tests for the Card model.

Reference: /docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 1)
"""

import pytest

from mtg_analyzer.models.cards.card import Card


def make_creature(**overrides) -> Card:
    defaults = dict(
        id="11111111-1111-1111-1111-111111111111",
        name="Grizzly Bears",
        type_line="Creature — Bear",
        mana_cost={"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0},
        converted_mana_cost=1,
        color_identity={"G"},
        is_creature=True,
        power=2,
        toughness=2,
        oracle_text="",
    )
    defaults.update(overrides)
    return Card(**defaults)


def make_land(**overrides) -> Card:
    defaults = dict(
        id="22222222-2222-2222-2222-222222222222",
        name="Island",
        type_line="Basic Land — Island",
        mana_cost={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        converted_mana_cost=0,
        color_identity=set(),
        is_land=True,
    )
    defaults.update(overrides)
    return Card(**defaults)


class TestCreateCreature:
    def test_creature_has_power_and_toughness(self):
        card = make_creature()
        assert card.is_creature is True
        assert card.power == 2
        assert card.toughness == 2

    def test_creature_type_flags(self):
        card = make_creature()
        assert card.is_instant is False
        assert card.is_sorcery is False
        assert card.is_land is False


class TestCreateLand:
    def test_land_has_no_power_or_toughness(self):
        card = make_land()
        assert card.is_land is True
        assert card.power is None
        assert card.toughness is None

    def test_land_default_mana_cost_is_zeroed(self):
        card = Card(
            id="33333333-3333-3333-3333-333333333333",
            name="Wastes",
            type_line="Basic Land",
            is_land=True,
        )
        assert card.mana_cost == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}


class TestValidation:
    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            make_land(name="")

    def test_blank_name_raises(self):
        with pytest.raises(ValueError):
            make_land(name="   ")

    def test_empty_type_line_raises(self):
        with pytest.raises(ValueError):
            make_land(type_line="")

    def test_power_without_creature_raises(self):
        with pytest.raises(ValueError):
            make_land(power=1)

    def test_toughness_without_creature_raises(self):
        with pytest.raises(ValueError):
            make_land(toughness=1)

    def test_invalid_color_identity_raises(self):
        with pytest.raises(ValueError):
            make_land(color_identity={"X"})

    def test_creature_without_power_toughness_is_allowed(self):
        card = make_creature(power=None, toughness=None)
        assert card.power is None
        assert card.toughness is None


class TestPartner:
    def test_partner_with_named_card(self):
        card = make_creature(has_partner=True, partner_with="Thrasios, Triton Hero")
        assert card.has_partner is True
        assert card.partner_with == "Thrasios, Triton Hero"

    def test_default_has_no_partner(self):
        card = make_creature()
        assert card.has_partner is False
        assert card.partner_with is None

    def test_has_clean_partner_with_true_when_unset(self):
        assert make_creature().has_clean_partner_with is True

    def test_has_clean_partner_with_true_for_a_bare_name(self):
        card = make_creature(has_partner=True, partner_with="Thrasios, Triton Hero")
        assert card.has_clean_partner_with is True

    def test_has_clean_partner_with_false_for_a_pre_fix_row_with_reminder_text(self):
        # A row cached before the scryfall_client._partner_with reminder-text
        # fix — see LazyCardLoader.load_cards, which refetches these.
        card = make_creature(
            has_partner=True,
            partner_with="Frodo, Adventurous Hobbit (When this creature enters, ...)",
        )
        assert card.has_clean_partner_with is False


class TestAsCopy:
    """`Card.as_copy` — the copiable-values snapshot a `become_copy` effect
    mutates a `GameObject` with (RULE 706.2)."""

    def test_plain_copy_matches_the_original(self):
        original = make_creature(name="Grave Titan", power=6, toughness=6,
                                  oracle_text="Deathtouch")
        copy = original.as_copy()
        assert copy is not original
        assert (copy.name, copy.power, copy.toughness, copy.oracle_text) == (
            "Grave Titan", 6, 6, "Deathtouch",
        )
        assert copy.type_line == original.type_line

    def test_add_subtypes_appends_after_the_dash(self):
        original = make_creature(type_line="Creature — Zombie Giant")
        copy = original.as_copy(add_subtypes=["Illusion"])
        assert copy.type_line == "Creature — Zombie Giant Illusion"
        assert copy.is_creature

    def test_add_types_inserts_before_the_dash(self):
        original = make_creature(type_line="Creature — Bear")
        copy = original.as_copy(add_types=["Enchantment"])
        assert copy.type_line == "Creature Enchantment — Bear"
        assert copy.is_enchantment

    def test_add_types_with_no_existing_subtype(self):
        original = Card(id="art", name="Sol Ring", type_line="Artifact")
        copy = original.as_copy(add_types=["Enchantment"])
        assert copy.type_line == "Artifact Enchantment"
        assert copy.is_enchantment and copy.is_artifact


class TestSerialization:
    def test_to_dict_round_trip_creature(self):
        card = make_creature()
        data = card.to_dict()
        restored = Card.from_dict(data)
        assert restored == card

    def test_to_dict_round_trip_land(self):
        card = make_land()
        data = card.to_dict()
        restored = Card.from_dict(data)
        assert restored == card

    def test_to_dict_is_json_compatible_types(self):
        card = make_creature()
        data = card.to_dict()
        assert isinstance(data["color_identity"], list)
        assert isinstance(data["mana_cost"], dict)

    def test_from_dict_missing_optional_fields_uses_defaults(self):
        card = Card.from_dict(
            {"id": "abc", "name": "Forest", "type_line": "Basic Land — Forest"}
        )
        assert card.oracle_text == ""
        assert card.is_legendary is False
        assert card.partner_with is None
        # Back-face fields absent on a legacy row default to empty.
        assert card.layout == ""
        assert card.has_back_face is False
        assert card.back_name == ""
        # Flavor name absent on a legacy row (predates the field) defaults blank.
        assert card.flavor_name == ""

    def test_flavor_name_round_trips(self):
        card = make_creature(name="Zilortha, Strength Incarnate", flavor_name="Godzilla, King of the Monsters")
        restored = Card.from_dict(card.to_dict())
        assert restored.flavor_name == "Godzilla, King of the Monsters"
        assert restored == card

    def test_to_dict_round_trip_double_faced_card(self):
        card = Card(
            id="dfc",
            name="Delver of Secrets // Insectile Aberration",
            type_line="Creature — Human Wizard",
            is_creature=True,
            power=1,
            toughness=1,
            image_uri_normal="https://img.example/delver.jpg",
            layout="transform",
            back_name="Insectile Aberration",
            back_type_line="Creature — Insect",
            back_oracle_text="Flying",
            back_power=3,
            back_toughness=2,
            back_image_uri_normal="https://img.example/aberration.jpg",
        )
        data = card.to_dict()
        assert data["has_back_face"] is True  # derived, exposed for the frontend
        restored = Card.from_dict(data)
        assert restored == card
        assert restored.is_transforming is True
        assert restored.back_toughness == 2


class TestDunderMethods:
    def test_repr_contains_name(self):
        card = make_creature()
        assert "Grizzly Bears" in repr(card)

    def test_eq_same_data(self):
        assert make_creature() == make_creature()

    def test_eq_different_data(self):
        assert make_creature() != make_land()

    def test_eq_against_non_card(self):
        assert make_creature() != "not a card"

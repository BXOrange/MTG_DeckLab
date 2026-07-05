"""Tests for the server-side decklist parser.

Reference: frontend/src/js/parser.js (the client-side counterpart this
mirrors) and backend/Done_Backend.md "HTTP API foundation".
"""

from mtg_analyzer.parser.deckliste_parser import parse_deck_sections

SAMPLE_COMMANDER = "1 Krenko, Mob Boss\n"

SAMPLE_MAINBOARD = "\n".join(f"1 Goblin {i}" for i in range(37)) + "\n62 Mountain\n"


def legal_deck(**overrides):
    kwargs = dict(commander_text=SAMPLE_COMMANDER, mainboard_text=SAMPLE_MAINBOARD, sideboard_text="")
    kwargs.update(overrides)
    return parse_deck_sections(**kwargs)


class TestCardLineParsing:
    def test_qty_x_name_format(self):
        result = parse_deck_sections(mainboard_text="4x Lightning Bolt")
        assert result.main_deck == result.main_deck  # sanity
        assert [c.to_dict() for c in result.main_deck] == [{"name": "Lightning Bolt", "qty": 4}]

    def test_qty_space_name_format(self):
        result = parse_deck_sections(mainboard_text="1 Sol Ring")
        assert [c.to_dict() for c in result.main_deck] == [{"name": "Sol Ring", "qty": 1}]

    def test_blank_lines_and_comments_ignored(self):
        text = "1 Sol Ring\n\n# a comment\n// another comment\n1 Mind Stone\n"
        result = parse_deck_sections(mainboard_text=text)
        assert len(result.main_deck) == 2

    def test_unparseable_line_reports_error(self):
        result = parse_deck_sections(mainboard_text="not a valid line")
        assert len(result.parse_errors) == 1
        assert "not a valid line" in result.parse_errors[0]

    def test_tag_marker_stripped(self):
        result = parse_deck_sections(mainboard_text="1 Sol Ring *MVP*")
        assert result.main_deck[0].name == "Sol Ring"

    def test_set_suffix_stripped(self):
        result = parse_deck_sections(mainboard_text="1 Sol Ring (LTR) 123")
        assert result.main_deck[0].name == "Sol Ring"

    def test_foil_star_marker_stripped(self):
        # Foil markers ("Sol Ring ★") aren't part of the name and break
        # resolution — strip them, collapsing the leftover space.
        assert parse_deck_sections(mainboard_text="1 Sol Ring ★").main_deck[0].name == "Sol Ring"
        assert parse_deck_sections(mainboard_text="1 ★Sol Ring").main_deck[0].name == "Sol Ring"
        assert parse_deck_sections(mainboard_text="1 Sol☆Ring").main_deck[0].name == "SolRing"

    def test_empty_name_after_stripping_reports_error(self):
        result = parse_deck_sections(mainboard_text="1 *MVP*")
        assert any("Leerer Kartenname" in e for e in result.parse_errors)


class TestMerging:
    def test_duplicate_names_merged_case_insensitively(self):
        text = "1 Mountain\n1 mountain\n2 MOUNTAIN\n"
        result = parse_deck_sections(mainboard_text=text)
        assert len(result.main_deck) == 1
        assert result.main_deck[0].qty == 4

    def test_all_cards_combines_commander_and_mainboard(self):
        result = parse_deck_sections(commander_text="1 Krenko, Mob Boss", mainboard_text="1 Sol Ring")
        names = {c.name for c in result.all_cards}
        assert names == {"Krenko, Mob Boss", "Sol Ring"}

    def test_sideboard_excluded_from_total_count(self):
        result = parse_deck_sections(mainboard_text="1 Sol Ring", sideboard_text="1 Negate\n1 Pyroblast")
        assert result.total_count == 1
        assert len(result.sideboard) == 2


class TestStructuralValidation:
    def test_legal_100_card_singleton_deck(self):
        result = legal_deck()
        assert result.total_count == 100
        assert result.validation.is_legal is True
        assert result.validation.errors == []

    def test_no_commander_warns_but_not_illegal_by_itself(self):
        result = parse_deck_sections(mainboard_text=SAMPLE_MAINBOARD + "1 Krenko, Mob Boss\n")
        assert any("Kein Commander" in w for w in result.validation.warnings)

    def test_too_many_commanders_is_illegal(self):
        result = legal_deck(commander_text="1 Thrasios, Triton Hero\n1 Tymna the Weaver\n1 Third Commander\n")
        assert result.validation.is_legal is False
        assert any("Zu viele Commander" in e for e in result.validation.errors)

    def test_wrong_card_count_is_illegal(self):
        result = parse_deck_sections(commander_text=SAMPLE_COMMANDER, mainboard_text="1 Sol Ring")
        assert result.validation.is_legal is False
        assert any("erwartet werden 100" in e for e in result.validation.errors)

    def test_non_basic_land_duplicate_is_illegal(self):
        result = legal_deck(mainboard_text=SAMPLE_MAINBOARD.replace("62 Mountain", "2 Sol Ring\n60 Mountain"))
        assert result.validation.is_legal is False
        assert any("Sol Ring" in e and "Singleton" in e for e in result.validation.errors)

    def test_basic_land_duplicates_allowed(self):
        result = legal_deck()
        assert not any("Mountain" in e for e in result.validation.errors)

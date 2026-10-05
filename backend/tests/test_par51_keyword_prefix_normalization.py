"""PAR-51 — Scryfall's spurious ``Jump`` must not split Jump-start."""

from mtg_analyzer.parser.oracle.normalize import normalize


def test_unregistered_jump_prefix_does_not_strip_jump_start_keyword():
    assert normalize("Jump-start", keywords=["Jump", "Jump-start"]) == "jump-start"


def test_unregistered_ability_word_with_spaced_dash_is_still_stripped():
    assert normalize("Flavor Label — Draw a card.", keywords=["Flavor Label"]) == "draw a card."

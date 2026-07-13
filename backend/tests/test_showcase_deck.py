"""The showcase Commander deck parses and is structurally legal.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md — this committed decklist is the
coverage fixture for the oracle-text -> effect parser (keywords, one-shot
effects, and "enters tapped" replacement lands).
"""

from pathlib import Path

import mtg_analyzer
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections

SHOWCASE_DECK = (
    Path(mtg_analyzer.__file__).parent / "data" / "decks" / "showcase_commander.txt"
)


def load_sections(path: Path) -> tuple[str, str]:
    """Split the fixture on its exact '// Commander' / '// Mainboard' marker LINES.

    (Substring splitting is unsafe: those literals also appear in the file's
    own header prose, and card names can contain '//', e.g. split cards.)
    """
    section = None
    buckets: dict[str, list[str]] = {"commander": [], "mainboard": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "// Commander":
            section = "commander"
        elif stripped == "// Mainboard":
            section = "mainboard"
        elif section is not None:
            buckets[section].append(line)
    return "\n".join(buckets["commander"]), "\n".join(buckets["mainboard"])


def test_showcase_deck_is_commander_legal():
    commander_text, mainboard_text = load_sections(SHOWCASE_DECK)
    deck = parse_deck_sections(commander_text=commander_text, mainboard_text=mainboard_text)

    assert deck.parse_errors == []
    assert [c.name for c in deck.commanders] == ["Kenrith, the Returned King"]
    assert deck.total_count == 100
    assert deck.validation.is_legal, deck.validation.errors
    assert deck.validation.warnings == []


def test_token_makers_are_present():
    # The deck's token-makers produce exactly the tokens seeded in tokens.json.
    _, mainboard_text = load_sections(SHOWCASE_DECK)
    deck = parse_deck_sections(mainboard_text=mainboard_text)
    names = {c.name for c in deck.main_deck}
    assert {
        "Prosperous Innkeeper",  # Treasure
        "Thraben Inspector",     # Clue
        "Gilded Goose",          # Food
        "Grave Titan",           # Zombie
        "Raise the Alarm",       # Soldier
    } <= names

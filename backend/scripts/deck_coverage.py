#!/usr/bin/env python3
"""Measure oracle-parser/hand-authoring coverage for one or more saved decks.

MEC-44 (docs/implementation-state/BACKLOG.md): the reusable replacement for
the one-off diagnosis script MEC-43's "make every cEDH deck playable" ticket
kept hand-rolling. "Covered" means exactly what `coverage_report.py`'s own
`measure()` means: the oracle parser returns MODELED, **or** the card is
hand-registered in `game/card_catalogue` (AUTHORED) — checked via
`is_registered(card.name)`, the *canonical* `Card.name`, not whatever text a
decklist happens to print. That distinction is the bug this script exists to
stop repeating: a double-faced card's decklist line is usually just its front
face ("Ojer Axonil, Deepest Might"), but `is_registered`/the ability catalogue
key off `Card.name`'s full "Front // Back" form — looking up the front-face
text alone under-reports coverage for every DFC in the deck.

Usage (from backend/, venv active):
  python scripts/deck_coverage.py                       # every saved deck
  python scripts/deck_coverage.py "cEDH staples 2"       # one deck, by name
  python scripts/deck_coverage.py --uncovered "K'rrik cEDH"  # list gaps too
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer.game.card_registry import is_authored_card  # noqa: E402
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections  # noqa: E402
from mtg_analyzer.parser.oracle import parse_oracle  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services.deck_database import DeckDatabase, DEFAULT_DECKS_DB_PATH  # noqa: E402


def deck_coverage(deck, db: CardDatabase) -> tuple[int, int, list[str], list[str]]:
    """Return (total_unique, covered_unique, uncovered_names, unresolved_names).

    `uncovered_names` are real, resolved cards that are neither AUTHORED nor
    MODELED. `unresolved_names` are decklist lines that didn't resolve to a
    cached card at all (a real gap in their own right, but a different one —
    an import/cache problem, not a parser-coverage one).
    """
    parsed = parse_deck_sections(
        commander_text=deck.commander_text or "",
        mainboard_text=deck.mainboard_text or "",
        is_cube=deck.is_cube,
    )
    total = covered = 0
    uncovered: list[str] = []
    unresolved: list[str] = []
    for entry in parsed.all_cards:
        card = db.get_card(entry.name)
        if card is None:
            unresolved.append(entry.name)
            continue
        total += 1
        # `card.name` is the canonical name (a DFC's own "Front // Back"
        # form) — the one thing both `is_registered` and the oracle parser
        # key off, regardless of how the decklist line spelled it.
        if is_authored_card(card) or parse_oracle(card).modeled:
            covered += 1
        else:
            uncovered.append(card.name)
    return total, covered, sorted(set(uncovered)), sorted(set(unresolved))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="deck name(s) to measure; omit for every saved deck")
    parser.add_argument("--uncovered", action="store_true", help="list uncovered/unresolved card names too")
    parser.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--decks-db", type=Path, default=DEFAULT_DECKS_DB_PATH)
    args = parser.parse_args()

    db = CardDatabase(args.card_db)
    deck_db = DeckDatabase(args.decks_db)
    decks = deck_db.list_decks()
    if args.names:
        wanted = {n.lower() for n in args.names}
        decks = [d for d in decks if d.name.lower() in wanted]
        missing = wanted - {d.name.lower() for d in decks}
        for name in missing:
            print(f"no saved deck named {name!r}")

    for deck in decks:
        total, covered, uncovered, unresolved = deck_coverage(deck, db)
        note = f" ({len(unresolved)} unresolved)" if unresolved else ""
        print(f"{deck.name}: {covered}/{total}{note}")
        if args.uncovered:
            for name in uncovered:
                print(f"    uncovered  {name}")
            for name in unresolved:
                print(f"    unresolved {name}")


if __name__ == "__main__":
    main()

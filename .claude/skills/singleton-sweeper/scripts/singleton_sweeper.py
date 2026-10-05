#!/usr/bin/env python3
"""Find other unclaimed Oracle-text clauses shaped like a parser singleton."""

from __future__ import annotations

import argparse
from collections import defaultdict
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
import sys

# This skill script lives outside the package tree. Locate the backend in the
# current checkout, while allowing an explicit path for out-of-tree use.
def _find_backend() -> Path:
    import os

    configured = os.environ.get("MTG_BACKEND_DIR")
    if configured:
        backend = Path(configured).resolve()
        if (backend / "mtg_analyzer").is_dir():
            return backend
        sys.exit(f"MTG_BACKEND_DIR does not contain mtg_analyzer: {backend}")

    cwd = Path.cwd().resolve()
    here = Path(__file__).resolve()
    for parent in [cwd, *cwd.parents, *here.parents]:
        if (parent / "mtg_analyzer").is_dir():
            return parent
        if (parent / "backend" / "mtg_analyzer").is_dir():
            return parent / "backend"
    sys.exit("could not locate backend/; run from the repository or set MTG_BACKEND_DIR")


sys.path.insert(0, str(_find_backend()))

from mtg_analyzer.config import DB_PATH  # noqa: E402
from mtg_analyzer.models.cards.card import Card  # noqa: E402
from mtg_analyzer.parser.oracle.gate import parse_oracle  # noqa: E402
from mtg_analyzer.parser.oracle.processing_list import abstract_clause  # noqa: E402


_WORD_RE = re.compile(r"[a-z]+")
_GENERIC_WORDS = frozenset(
    {
        "a", "an", "and", "are", "be", "been", "being", "but", "by", "can",
        "do", "does", "for", "from", "has", "have", "if", "in", "into", "is",
        "it", "its", "of", "on", "or", "that", "the", "their", "then", "this",
        "to", "until", "was", "were", "when", "whenever", "which", "with",
        "you", "your", "target", "creature", "turn", "end",
    }
)
# A broad floor for discovery; parser_probe.py establishes actual scope.
DEFAULT_SIMILARITY_THRESHOLD = 0.5
# Close text matches may be useful even when they share few distinctive words.
HIGH_SIMILARITY_THRESHOLD = 0.72


def _load_cards(db_path: Path) -> list[Card]:
    if not db_path.is_file():
        raise SystemExit(f"card cache does not exist: {db_path}")
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute("SELECT data FROM cards ORDER BY name").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise SystemExit(f"could not read card cache {db_path}: {exc}") from exc
    return [Card.from_dict(json.loads(row[0])) for row in rows]


def _lookup_card(cards: list[Card], name: str) -> Card:
    folded = name.casefold()
    front = name.split("/", 1)[0].strip().casefold()
    for card in cards:
        if card.name.casefold() == folded or card.flavor_name.casefold() == folded:
            return card
    for card in cards:
        if card.name.casefold().startswith(front + " // "):
            return card
    suggestions = sorted(
        cards,
        key=lambda card: max(
            SequenceMatcher(None, folded, card.name.casefold()).ratio(),
            SequenceMatcher(None, folded, card.flavor_name.casefold()).ratio()
            if card.flavor_name
            else 0.0,
        ),
        reverse=True,
    )[:8]
    print(f"no exact cached card named {name!r}", file=sys.stderr)
    print("nearby cached names:", file=sys.stderr)
    for suggestion in suggestions:
        print(f"  {suggestion.name}", file=sys.stderr)
    raise SystemExit(2)


def _best_match(target_clause: str, target_template: str, clause: str) -> float:
    if abstract_clause(clause).casefold() == target_template.casefold():
        return 1.0
    return SequenceMatcher(None, target_clause.casefold(), clause.casefold()).ratio()


def _shared_content_words(left: str, right: str) -> int:
    left_words = set(_WORD_RE.findall(left.casefold())) - _GENERIC_WORDS
    right_words = set(_WORD_RE.findall(right.casefold())) - _GENERIC_WORDS
    return len(left_words & right_words)


def _sweep(args: argparse.Namespace) -> int:
    all_cards = _load_cards(args.card_db)
    target = _lookup_card(all_cards, args.name)
    target_result = parse_oracle(target)
    target_gaps = [clause.strip() for clause in target_result.unclaimed if clause.strip()]
    total = len(all_cards)

    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be at least 1")
        selected = all_cards[: args.limit]
        if all(card.id != target.id for card in selected):
            selected = selected[: args.limit - 1] + [target]
        all_cards = selected

    print(
        f"{target.name}: parser={target_result.coverage}, "
        f"{len(target_gaps)} unclaimed clause(s)"
    )
    print(f"Scanning {len(all_cards)} of {total} cached cards.")
    if not target_gaps:
        print("No parser-unclaimed clause to sweep; re-check the singleton queue entry.")
        return 0

    scanned: list[tuple[str, str]] = []
    target_name = target.name.casefold()
    for card in all_cards:
        if card.name.casefold() == target_name:
            continue
        result = parse_oracle(card)
        if result.never_supported:
            continue
        for clause in result.unclaimed:
            text = clause.strip()
            if text:
                scanned.append((card.name, text))

    for gap_index, target_clause in enumerate(target_gaps, start=1):
        target_template = abstract_clause(target_clause)
        groups: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
        for card_name, clause in scanned:
            score = _best_match(target_clause, target_template, clause)
            same_template = abstract_clause(clause).casefold() == target_template.casefold()
            if score < args.threshold or (
                not same_template
                and score < HIGH_SIMILARITY_THRESHOLD
                and _shared_content_words(target_clause, clause) < 2
            ):
                continue
            template = abstract_clause(clause)
            previous = groups[template].get(card_name)
            if previous is None or score > previous[0]:
                groups[template][card_name] = (score, clause)

        exact_template = next(
            (group for template, group in groups.items()
             if template.casefold() == target_template.casefold()),
            {},
        )
        near_groups = [
            (template, entries)
            for template, entries in groups.items()
            if template.casefold() != target_template.casefold()
        ]
        near_groups.sort(
            key=lambda item: (-len(item[1]), -max(hit[0] for hit in item[1].values()), item[0])
        )

        print(f"\n--- Target gap {gap_index} ---")
        print(f"  {target_clause}")
        print(f"  template: {target_template}")
        print(f"  exact-template siblings: {len(exact_template)}")
        _print_group(exact_template, args.show, exact=True)

        print(f"  fuzzy neighboring templates (threshold {args.threshold:.2f}):")
        if not near_groups:
            print("    none")
        for template, entries in near_groups[: args.top]:
            best_score = max(hit[0] for hit in entries.values())
            print(f"    {len(entries)} card(s), best text score {best_score:.2f}: {template}")
            _print_group(entries, args.show, indent="      ")

    print(
        "\nText similarity is discovery evidence only. Confirm shared rules meaning "
        "and measure actual SOLO/ALSO-BLOCKED scope with parser_probe.py before "
        "creating or promoting a parser ticket."
    )
    return 0


def _print_group(
    entries: dict[str, tuple[float, str]],
    limit: int,
    *,
    exact: bool = False,
    indent: str = "    ",
) -> None:
    if not entries:
        print(f"{indent}(none)")
        return
    ordered = sorted(entries.items(), key=lambda item: (-item[1][0], item[0].casefold()))
    for card_name, (score, clause) in ordered[:limit]:
        label = "exact template" if exact else f"text {score:.2f}"
        print(f"{indent}{card_name} [{label}]")
        print(f"{indent}  {clause}")
    if len(ordered) > limit:
        print(f"{indent}... {len(ordered) - limit} more card(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="exact cached card name from the singleton queue")
    parser.add_argument("--card-db", type=Path, default=DB_PATH)
    parser.add_argument("--limit", type=int, default=None, help="scan only N cached cards (smoke tests only)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help="minimum fuzzy text similarity",
    )
    parser.add_argument("--top", type=int, default=8, help="nearby template groups to show per target clause")
    parser.add_argument("--show", type=int, default=12, help="cards to show per candidate group")
    args = parser.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between 0 and 1")
    if args.top < 1 or args.show < 1:
        parser.error("--top and --show must be at least 1")
    raise SystemExit(_sweep(args))


if __name__ == "__main__":
    main()

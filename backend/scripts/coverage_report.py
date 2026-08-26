#!/usr/bin/env python3
"""Measure card-modeling coverage over the whole cache and rank the backlog.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE PROCESSING LIST"),
and the plan (Phase 0b/0d). Replaces the old ad-hoc REPL ritual with one
reproducible command that also *persists* results to the engineering DB
(`services/coverage_db.py`), so a re-run only re-parses cards whose content
signature changed — the deterministic pipeline gets cheaper each time and no
LLM is involved at any step.

"Covered" here means the card actually *behaves*: the oracle parser returned
MODELED, **or** the card is hand-registered in `game/ability_catalogue.py`
(AUTHORED). The processing-list ranking counts only *uncovered* cards' unclaimed
clauses, template-abstracted — that ranking is the build order for the next
handlers.

Usage (from backend/, venv active):
  python scripts/coverage_report.py [--top N] [--limit N] [--json OUT] [--no-db]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer.game.ability_catalogue import is_registered  # noqa: E402
from mtg_analyzer.parser.oracle import NEVER_SUPPORTED, abstract_clause, parse_oracle  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services import coverage_db as cov  # noqa: E402


def measure(cards, cov_db, use_ledger=True):
    """Return (total, covered, never_supported, template_counter). Reuses ledger rows when fresh."""
    total = covered = never_supported = 0
    template_cards: Counter[str] = Counter()
    reused = parsed = 0

    for card in cards:
        total += 1
        chash = cov.content_hash(card)
        row = cov_db.get(chash) if (cov_db and use_ledger) else None

        if row is not None:
            reused += 1
            is_covered, unclaimed, coverage = row.covered, row.unclaimed, row.coverage
        else:
            parsed += 1
            authored = is_registered(getattr(card, "name", "") or "")
            result = parse_oracle(card)
            source = "authored" if authored else "parser"
            if result.coverage == NEVER_SUPPORTED:
                coverage = cov.NEVER_SUPPORTED
            else:
                coverage = cov.MODELED if result.modeled else cov.UNMODELED
            is_covered = authored or result.modeled
            unclaimed = [] if is_covered else list(result.unclaimed)
            if cov_db:
                cov_db.upsert(chash, getattr(card, "name", "") or "",
                              coverage, source, unclaimed)

        if coverage == cov.NEVER_SUPPORTED:
            never_supported += 1
        elif is_covered:
            covered += 1
        else:
            # count each template once per card (dedup) — cards, not clauses
            for template in {abstract_clause(c) for c in unclaimed if c.strip()}:
                template_cards[template] += 1

    return total, covered, never_supported, template_cards, reused, parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=40, help="how many backlog templates to print")
    parser.add_argument("--limit", type=int, default=None, help="measure only the first N cards (quick test)")
    parser.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--coverage-db", type=Path, default=cov.DEFAULT_COVERAGE_DB_PATH)
    parser.add_argument("--json", type=Path, default=None, help="also write the full report as JSON here")
    parser.add_argument("--no-db", action="store_true", help="don't read/write the engineering ledger")
    args = parser.parse_args()

    cards = CardDatabase(args.card_db).list_cards()
    if args.limit is not None:
        cards = cards[: args.limit]

    cov_db = None if args.no_db else cov.CoverageDatabase(args.coverage_db)
    total, covered, never_supported, template_cards, reused, parsed = measure(cards, cov_db)

    ranked = sorted(template_cards.items(), key=lambda kv: (-kv[1], kv[0]))
    handled = cov_db.handled_templates() if cov_db else {}
    fraction = (covered / total) if total else 1.0

    if cov_db:
        cov_db.record_snapshot(total, covered, ranked[: args.top])

    print(f"\nCoverage: {covered}/{total} = {fraction:.1%} covered "
          f"(reused {reused} from ledger, parsed {parsed}, "
          f"{never_supported} never-supported [Stickers, RULE 123])")
    print(f"PARSER_VERSION={cov.PARSER_VERSION}  card_db={args.card_db}")
    print(f"\nTop {args.top} backlog templates (cards blocked → template):")
    for template, n in ranked[: args.top]:
        mark = " [handled?]" if template in handled else ""
        print(f"  {n:5d}  {template}{mark}")

    if args.json:
        args.json.write_text(json.dumps({
            "total": total, "covered": covered, "never_supported": never_supported,
            "fraction": fraction, "reused": reused, "parsed": parsed,
            "backlog": [{"template": t, "cards": n} for t, n in ranked],
        }, indent=2), encoding="utf-8")
        print(f"\nWrote JSON report to {args.json}")

    if cov_db:
        cov_db.close()


if __name__ == "__main__":
    main()

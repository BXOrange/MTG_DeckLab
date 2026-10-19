"""PAR-169: ``HANDLERS`` order is semantics, so no two rows may claim one real clause with different IR by accident.

Every clause the parser hands the handler table while parsing the whole card cache is offered to every eligible
row. Two rows that both claim it with different IR are a shadowing conflict unless the pair is declared:

* the later row is a declared ``fallback_for`` the earlier one (and really comes after it), or
* the earlier row is context-gated (``self_subject_only`` &c.) and the later one is not: the context-specific
  reading of a pronoun deliberately overrides the default one.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from mtg_analyzer.parser.oracle import gate
from mtg_analyzer.parser.oracle.catalogue import handlers as H
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards.card import Card

#: The `ClauseReading` facts an `EffectHandler.requires` can ask for.
_FACTS = ("self_subject", "previous_subject", "group_subject", "previous_selector", "attached_subject")

#: Same-clause/different-IR pairs that are order-dependent by design *beyond* the two declared mechanisms.
#: Empty on purpose: add an entry only with a why-comment, and prefer `fallback_for`.
ALLOWED_CONFLICTS: dict[tuple[str, str], str] = {}


def _gates(handler) -> set[str]:
    return {f for f in _FACTS if getattr(handler.requires, f)}


def _ir(specs) -> str:
    return json.dumps([s.to_dict() for s in specs], sort_keys=True, default=repr)


def test_fallback_rows_come_after_their_primary():
    position = {}
    for i, h in enumerate(H.HANDLERS):
        position.setdefault(h.name, []).append(i)
    for i, h in enumerate(H.HANDLERS):
        for primary in h.fallback_for:
            assert primary in position, f"{h.name} is a fallback for unknown row {primary}"
            assert min(position[primary]) < i, f"{h.name} must come after its primary {primary}"


@pytest.mark.full_cache
@pytest.mark.timeout(900)  # parses the whole card cache without the parse memo, then re-offers every clause to every row
def test_no_two_eligible_rows_claim_one_clause_with_different_ir():
    with sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        cards = [Card.from_dict(json.loads(row[0])) for row in conn.execute("SELECT data FROM cards")]
    seen: set[tuple[str, frozenset[str]]] = set()
    original = H._match_clause_once

    def record(clause, *, reading):
        seen.add((clause, frozenset(f for f in _FACTS if getattr(reading, f))))
        return original(clause, reading=reading)

    saved = dict(gate._PARSE_CACHE)
    gate._PARSE_CACHE.clear()  # a warm parse cache would never reach the handler table
    H._match_clause_once = record
    try:
        for card in cards:
            gate.parse_oracle(card)
    finally:
        H._match_clause_once = original
        gate._PARSE_CACHE.clear()
        gate._PARSE_CACHE.update(saved)
    assert len(seen) > 10_000, "the full card cache is not loaded"

    order = {id(h): i for i, h in enumerate(H.HANDLERS)}
    conflicts: set[tuple[str, str]] = set()
    examples: dict[tuple[str, str], str] = {}
    for clause, on in sorted(seen, key=lambda item: (item[0], sorted(item[1]))):
        claims = []
        for handler in H.HANDLERS:
            if not _gates(handler) <= on:
                continue
            specs = handler.match(clause)
            if specs is not None:
                claims.append((handler, _ir(specs)))
        if not claims:
            continue
        first, first_ir = claims[0]
        for handler, ir in claims[1:]:
            if ir == first_ir:
                continue
            if first.name in handler.fallback_for:
                continue
            if _gates(first) and not _gates(handler):
                continue
            pair = (first.name, handler.name)
            if pair in ALLOWED_CONFLICTS:
                continue
            conflicts.add(pair)
            examples.setdefault(pair, clause)
    assert not conflicts, "undeclared same-clause/different-IR rows (declare fallback_for or retire one):\n" + "\n".join(
        f"  {a} shadows {b}: {examples[(a, b)]!r}" for a, b in sorted(conflicts)
    )

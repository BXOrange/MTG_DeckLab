"""One fresh, observed parse of the card pool for independent full-cache checks.

No disk memo or test verdicts are reused. Public parse_oracle still returns
fresh specs; only its private memo is warmed by this session's observed pass.
"""

from dataclasses import dataclass
from collections.abc import Iterable

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import gate
from mtg_analyzer.parser.oracle.catalogue import handlers as H

READING_FACTS = ("self_subject", "previous_subject", "group_subject", "previous_selector", "attached_subject")


@dataclass(frozen=True)
class FullCacheParse:
    cards: tuple[Card, ...]
    clauses: frozenset[tuple[str, frozenset[str]]]


def observe_card_pool(cards: Iterable[Card]) -> FullCacheParse:
    cards = tuple(cards)
    seen = set()
    original_match = H._match_clause_once
    original_memo = gate._PARSE_CACHE
    fresh_memo = {}

    def record(clause, *, reading):
        seen.add((clause, frozenset(f for f in READING_FACTS if getattr(reading, f))))
        return original_match(clause, reading=reading)

    gate._PARSE_CACHE = fresh_memo  # warm input must not hide handler visits
    H._match_clause_once = record
    try:
        for card in cards:
            gate.parse_oracle(card)
    finally:
        H._match_clause_once = original_match
        gate._PARSE_CACHE = original_memo
    # Only publish a completed pass. An exception leaves the original memo intact.
    original_memo.update(fresh_memo)
    return FullCacheParse(cards, frozenset(seen))

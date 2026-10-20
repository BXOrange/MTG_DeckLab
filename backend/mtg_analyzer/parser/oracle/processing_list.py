"""The processing list + coverage metric (docs/09 "THE PROCESSING LIST").

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE PROCESSING LIST + ANALYZER
MODULE", "THE COVERAGE GATE" consequence 3: "Coverage is the roadmap").

`parse_oracle` (the gate) tells us, per card, which ability lines it could not
claim. This module turns that residue across a *set* of cards into the two
artefacts docs/09 calls for:

* a **coverage metric** — what fraction of the cards are fully `MODELED`, and
* a **processing list** — the deduped, **template-abstracted** unclaimed
  clauses ranked by how many cards each would unlock. That ranking *is* the
  build order for the next handlers.

"Template-abstracted" means literals that don't change a clause's shape —
numbers, mana costs, the self-reference `~`, quoted names — are collapsed to
placeholders, so "deals 3 damage to target goblin" and "deals 5 damage to
target dwarf" fold to one template. The unit of the backlog is the template,
not the card (docs/09: a few hundred templates, not tens of thousands of cards).

Pure — **no `game/` imports** (front-end security boundary). It only reads
`ParseResult`s the gate already produced.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .gate import ParseResult, parse_oracle, unclaimed_spans
from .normalize import SELF

#: Literal-abstraction passes, applied in order, that fold a clause to its
#: template. Each collapses a shape-preserving literal to a placeholder.
_ABSTRACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(re.escape(SELF)), "<name>"),              # the self-reference
    (re.compile(r"\{[^}]+\}(?:\s*\{[^}]+\})*"), "<cost>"),  # a run of mana pips
    (re.compile(r"\d+"), "<n>"),                          # any number
    (re.compile(r'"[^"]+"'), "<name>"),                   # a quoted name
]


def abstract_clause(clause: str) -> str:
    """Collapse a clause's shape-preserving literals to placeholders (docs/09)."""
    text = clause.strip()
    for pattern, placeholder in _ABSTRACTIONS:
        text = pattern.sub(placeholder, text)
    return re.sub(r"\s+", " ", text).strip()


def unclaimed_work_units(card: Any, result: ParseResult) -> list[str]:
    """The unclaimed clauses of ``result`` narrowed to their minimal blocking part (PAR-175 M5).

    Each entry of ``result.unclaimed`` maps to the sentence or connector part that blocked it
    (`gate.unclaimed_spans`), or to itself when none isolates it. Ranking these groups cards by the
    sentence that actually needs a handler instead of by the whole printed line. Report only: the
    verdict still comes from ``unclaimed``.
    """
    spans = {entry.line: entry.span for entry in unclaimed_spans(card, result)}
    return [spans.get(line, line) for line in result.unclaimed]


@dataclass(frozen=True)
class TemplateEntry:
    """One processing-list row: a clause template and how many cards it blocks."""

    template: str
    cards: int  # number of cards with at least one unclaimed clause matching it

    def as_tuple(self) -> tuple[str, int]:
        return (self.template, self.cards)


@dataclass
class CoverageReport:
    """Cache-wide coverage + the ranked processing list (docs/09 metrics)."""

    total: int = 0
    modeled: int = 0
    #: Cards whose only unclaimed clauses are a permanent non-goal (Stickers,
    #: RULE 123 — `gate.NEVER_SUPPORTED`), not an ordinary backlog gap. Counted
    #: separately from `modeled` so the headline coverage fraction isn't
    #: inflated by cards that will never actually behave.
    never_supported: int = 0
    #: Processing list: templates ranked by cards-unlocked, descending.
    processing_list: list[TemplateEntry] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.processing_list is None:
            self.processing_list = []

    @property
    def modeled_fraction(self) -> float:
        return (self.modeled / self.total) if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "modeled": self.modeled,
            "never_supported": self.never_supported,
            "modeled_fraction": round(self.modeled_fraction, 4),
            "processing_list": [e.as_tuple() for e in self.processing_list],
        }


def coverage_report(
    results: Iterable[ParseResult],
    *,
    work_units: Callable[[ParseResult], list[str]] = lambda result: result.unclaimed,
) -> CoverageReport:
    """Aggregate `ParseResult`s into a coverage metric + ranked processing list.

    Each unclaimed clause is template-abstracted and counted **once per card**
    (a card that repeats a clause doesn't inflate its rank), so the count is
    "how many cards this template blocks" — the docs/09 unlock ranking. ``work_units`` picks the
    clauses to rank per result (default the whole unclaimed lines; `coverage_over_cards(by_span=True)`
    passes the minimal blocking sentences).
    """
    total = 0
    modeled = 0
    never_supported = 0
    template_cards: Counter[str] = Counter()

    for result in results:
        total += 1
        if result.modeled:
            modeled += 1
            continue
        if result.never_supported:
            never_supported += 1
            continue
        templates = {abstract_clause(c) for c in work_units(result) if c.strip()}
        for template in templates:
            template_cards[template] += 1

    ranked = [
        TemplateEntry(template=t, cards=n)
        for t, n in sorted(template_cards.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return CoverageReport(
        total=total, modeled=modeled, never_supported=never_supported, processing_list=ranked
    )


def coverage_over_cards(cards: Iterable[Any], *, by_span: bool = False) -> CoverageReport:
    """Convenience: run `parse_oracle` over ``cards`` and report coverage (``by_span``: rank minimal sentences)."""
    if not by_span:
        return coverage_report(parse_oracle(card) for card in cards)
    owner: dict[int, Any] = {}
    results = []
    for card in cards:
        result = parse_oracle(card)
        owner[id(result)] = card
        results.append(result)
    return coverage_report(results, work_units=lambda result: unclaimed_work_units(owner[id(result)], result))

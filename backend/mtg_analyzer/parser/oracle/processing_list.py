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
from typing import Any, Iterable

from .gate import ParseResult, parse_oracle
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
            "modeled_fraction": round(self.modeled_fraction, 4),
            "processing_list": [e.as_tuple() for e in self.processing_list],
        }


def coverage_report(results: Iterable[ParseResult]) -> CoverageReport:
    """Aggregate `ParseResult`s into a coverage metric + ranked processing list.

    Each unclaimed clause is template-abstracted and counted **once per card**
    (a card that repeats a clause doesn't inflate its rank), so the count is
    "how many cards this template blocks" — the docs/09 unlock ranking.
    """
    total = 0
    modeled = 0
    template_cards: Counter[str] = Counter()

    for result in results:
        total += 1
        if result.modeled:
            modeled += 1
            continue
        templates = {abstract_clause(c) for c in result.unclaimed if c.strip()}
        for template in templates:
            template_cards[template] += 1

    ranked = [
        TemplateEntry(template=t, cards=n)
        for t, n in sorted(template_cards.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return CoverageReport(total=total, modeled=modeled, processing_list=ranked)


def coverage_over_cards(cards: Iterable[Any]) -> CoverageReport:
    """Convenience: run `parse_oracle` over ``cards`` and report coverage."""
    return coverage_report(parse_oracle(card) for card in cards)

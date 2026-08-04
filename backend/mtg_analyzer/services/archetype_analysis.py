"""Heuristic archetype-likelihood scoring for a resolved decklist.

Reference: docs/implementation-state/BACKLOG.md's archetype-analysis
request, `services/archetype_database.py` (the catalogue this scores
against). There is no LLM integration in this codebase — this is a plain
heuristic over the deck's own cards, not a model call, so every scoring
number here is a project-defined constant (see the "no magic numbers"
convention in CLAUDE.md) rather than a tuned/learned weight.

Two independent signals are combined per archetype:

* **Signal cards** — the catalogue's hand-picked "core"/"support" staples
  for that archetype. A deck actually containing those specific cards is
  strong evidence, so they're weighted heavier than a text match.
* **Synergy patterns** — the catalogue's oracle-text regexes. A deck with
  many *unnamed* cards matching an archetype's mechanical pattern (e.g.
  "sacrifice a creature" for Aristocrats) is corroborating evidence even
  without the named staples, but weaker per hit, hence capped.

Each archetype is scored independently against its own `score_threshold`
(a per-archetype ceiling in the catalogue data, not a code constant) rather
than as a probability partition across archetypes — a deck can genuinely
read high on two archetypes at once (the app lets a deck carry two).

`detect_typal_signals` is a separate, catalogue-independent pass: EDH
"typal"/tribal decks aren't enumerated in the archetype catalogue (dozens of
tribes would go stale fast — see `archetype_database.py`'s docstring), so
tribal synergy is detected directly from the deck's own creature-type
distribution instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.archetype_database import default_archetype_database

#: A named ("core") signal card counts 3x as much as a "support" one — it's
#: the archetype's own build-around/most-iconic staple, not just a common
#: inclusion. (See CLAUDE.md "No magic numbers".)
SIGNAL_WEIGHT_CORE = 3

#: A "support" signal card is a common but non-defining inclusion — counted,
#: but at a quarter of a core card's weight.
SIGNAL_WEIGHT_SUPPORT = 1

#: Each nonland card whose oracle text matches one of the archetype's
#: synergy-pattern regexes contributes this many points to the pattern
#: score. Kept at 1 (vs. signal cards' 3/1) since a text-pattern match is a
#: weaker, more generic signal than a specific named staple.
PATTERN_MATCH_WEIGHT = 1

#: Ceiling on how many pattern matches count toward an archetype's score.
#: Without a cap, a very large or very generic-text-heavy deck could run up
#: an archetype's pattern score purely from deck size rather than genuine
#: thematic fit.
PATTERN_MATCH_CAP = 15

#: Named-card matches (signal_score) are weighted twice as heavily as the
#: (already-weighted) pattern score when combined into the raw score, since
#: a deck actually running an archetype's staples is stronger evidence than
#: incidental text matches.
SIGNAL_SCORE_MULTIPLIER = 2

#: How many top-scoring archetypes `score_archetypes` returns.
TOP_N_SUGGESTIONS = 5

#: A creature type must make up at least this share of the deck's creatures
#: to be reported as a typal/tribal signal — keeps a deck with 2 stray Elves
#: among 30 creatures from reading as "Elf Typal".
TYPAL_MIN_CREATURE_SHARE = 0.20


@dataclass
class ArchetypeScore:
    id: str
    label: str
    description: str
    percent: int
    matched_core: list[str]
    matched_support: list[str]
    pattern_match_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "percent": self.percent,
            "matchedCore": self.matched_core,
            "matchedSupport": self.matched_support,
            "patternMatchCount": self.pattern_match_count,
        }


@dataclass
class TypalSignal:
    creature_type: str
    count: int
    share: float

    def to_dict(self) -> dict[str, Any]:
        return {"creatureType": self.creature_type, "count": self.count, "share": self.share}


def _unique_by_name(cards: list[Card]) -> dict[str, Card]:
    """Dedupe a flat (possibly qty-expanded) card list by name, so e.g. 30
    copies of a basic land don't inflate a pattern-match count 30x."""
    by_name: dict[str, Card] = {}
    for card in cards:
        by_name.setdefault(card.name, card)
    return by_name


def score_archetypes(cards: list[Card]) -> list[ArchetypeScore]:
    """Score every catalogue archetype against `cards` (a flat, possibly
    qty-expanded card list — see `api/game.py`'s `expand_entries`), and
    return the top `TOP_N_SUGGESTIONS` by percent."""
    unique = _unique_by_name(cards)
    names = set(unique.keys())
    nonland_texts = [c.oracle_text or "" for c in unique.values() if not c.is_land]

    scores: list[ArchetypeScore] = []
    for entry in default_archetype_database().all_archetypes():
        core = entry["signal_cards"]["core"]
        support = entry["signal_cards"]["support"]
        matched_core = [name for name in core if name in names]
        matched_support = [name for name in support if name in names]
        signal_score = len(matched_core) * SIGNAL_WEIGHT_CORE + len(matched_support) * SIGNAL_WEIGHT_SUPPORT

        patterns = [re.compile(p, re.IGNORECASE) for p in entry["synergy_patterns"]]
        pattern_hits = sum(1 for text in nonland_texts if any(p.search(text) for p in patterns))
        pattern_score = min(pattern_hits, PATTERN_MATCH_CAP) * PATTERN_MATCH_WEIGHT

        raw_score = SIGNAL_SCORE_MULTIPLIER * signal_score + pattern_score
        percent = min(100, round(raw_score / entry["score_threshold"] * 100))

        scores.append(
            ArchetypeScore(
                id=entry["id"],
                label=entry["label"],
                description=entry["description"],
                percent=percent,
                matched_core=matched_core,
                matched_support=matched_support,
                pattern_match_count=pattern_hits,
            )
        )

    scores.sort(key=lambda s: s.percent, reverse=True)
    return scores[:TOP_N_SUGGESTIONS]


def detect_typal_signals(cards: list[Card]) -> list[TypalSignal]:
    """Group this deck's creatures by subtype (the part of `type_line`
    after the em dash) and report any type at or above
    `TYPAL_MIN_CREATURE_SHARE` of the creature base."""
    unique = _unique_by_name(cards)
    creatures = [c for c in unique.values() if c.is_creature]
    total = len(creatures)
    if total == 0:
        return []

    counts: dict[str, int] = {}
    for card in creatures:
        subtypes = _creature_subtypes(card.type_line)
        for subtype in subtypes:
            counts[subtype] = counts.get(subtype, 0) + 1

    signals = [
        TypalSignal(creature_type=subtype, count=count, share=round(count / total, 3))
        for subtype, count in counts.items()
        if count / total >= TYPAL_MIN_CREATURE_SHARE
    ]
    signals.sort(key=lambda s: s.share, reverse=True)
    return signals


def _creature_subtypes(type_line: str) -> list[str]:
    """"Creature — Elf Warrior" -> ["Elf", "Warrior"]. Non-creature and
    typeless lines (no em dash) yield nothing."""
    if "—" not in type_line:
        return []
    _, _, subtypes = type_line.partition("—")
    return [s for s in subtypes.strip().split() if s]

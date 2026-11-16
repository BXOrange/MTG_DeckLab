"""Filter-slot peeler (PAR-281): offer "with <quality>" to rows that already own the noun phrase.

A row's regex names the *operation* ("search your library for <criteria>, reveal it, put it into your
hand, then shuffle"); each row spells its own filter vocabulary, so a quality the row never wrote
("... a creature card **with defender** ...") leaves the whole clause unclaimed although the rest is
known-good. This is one ordered step that runs after every row declined (`handlers.match_clause`):

1. cut the single "with <quality>" out of the clause's noun phrase,
2. let the ordinary table claim the shorter clause, and
3. carry the cut quality into the spec the table produced -- as a param the engine already reads.

Fail-closed: the peel is accepted only when a *carrier* for the produced spec exists (today the library
search, whose ``criteria`` dict is `models.cards.card_query`'s vocabulary, so every key written here is
checked by the same predicate the search already uses). A quality that no carrier can express, a spec
the carrier does not know, a key collision, or a second "with" in the noun phrase all refuse -- the
quality is never dropped (a dropped filter would be a wrong-but-MODELED card).

RULE 701.19a: a search finds only cards that have the quality named. RULE 202.3: mana value. RULE
208/209 (power, toughness) are the printed values of a card outside the battlefield.

Pure regex + data -- no ``game/`` imports (security boundary).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ..spec import EffectSpec
from .keywords import KEYWORDS

#: Comparison words of a numeric quality -> the card_query bound key prefix they write.
_BOUND_BY_COMPARATOR = {"less": "max", "greater": "min"}

_NUMBER = r"\d+"
_COMPARATOR = r"(?P<cmp>less|greater)"

#: "with mana value 2" / "with mana value 4 or 5" (the exact value, or an OR of exact values).
_MANA_VALUE_EXACT_RE = re.compile(rf"mana value (?P<a>{_NUMBER})(?: or (?P<b>{_NUMBER}))?")
#: "with power 6 or greater" / "with toughness 2 or less".
_STAT_RE = re.compile(rf"(?P<stat>power|toughness) (?P<n>{_NUMBER}) or {_COMPARATOR}")
#: "with power or toughness 6 or greater": either printed stat meets the bound.
_STAT_EITHER_RE = re.compile(rf"power or toughness (?P<n>{_NUMBER}) or {_COMPARATOR}")
#: "with defender" / "with flashback or disturb": one or two keyword abilities the parser already knows.
_KEYWORD_RE = re.compile(r"(?P<a>[a-z]+)(?: or (?P<b>[a-z]+))?")

#: The clause shape every carrier shares: the quality sits in the first comma-free segment, which is
#: the noun phrase ("search your library for a creature card with defender" -- the next comma starts
#: the "reveal it, put it ..." tail).
_QUALITY_IN_NOUN_RE = re.compile(
    r"(?P<head>.*?search your library for [^,:]*?) with (?P<quality>[^,:]+?)(?P<tail>,.*|\.?)",
    re.DOTALL,
)

Criteria = dict[str, Any]


def _bounds(key: str, n: int, comparator: str) -> Criteria:
    return {f"{_BOUND_BY_COMPARATOR[comparator]}_{key}": n}


def _keyword_criteria(word: str) -> Optional[Criteria]:
    # Card.keywords holds the printed display name; card_query compares case-insensitively. Only a word
    # the keyword catalogue itself knows is read, so prose ("a mana ability") never becomes a keyword.
    if word not in KEYWORDS:
        return None
    return {"has_keyword": word}


def _or_of(alternatives: list[Criteria]) -> Criteria:
    return alternatives[0] if len(alternatives) == 1 else {"or": alternatives}


def quality_criteria(quality: str) -> Optional[Criteria]:
    """The `card_query` criteria for one "with <quality>" phrase, or ``None`` when the vocabulary lacks it."""
    quality = quality.strip()
    m = _MANA_VALUE_EXACT_RE.fullmatch(quality)
    if m:
        values = [int(m.group("a"))] + ([int(m.group("b"))] if m.group("b") else [])
        return _or_of([{"min_mana_value": v, "max_mana_value": v} for v in values])
    m = _STAT_RE.fullmatch(quality)
    if m:
        return _bounds(m.group("stat"), int(m.group("n")), m.group("cmp"))
    m = _STAT_EITHER_RE.fullmatch(quality)
    if m:
        n, cmp_word = int(m.group("n")), m.group("cmp")
        return {"or": [_bounds("power", n, cmp_word), _bounds("toughness", n, cmp_word)]}
    m = _KEYWORD_RE.fullmatch(quality)
    if m:
        words = [w for w in (m.group("a"), m.group("b")) if w]
        parts = [_keyword_criteria(w) for w in words]
        if all(p is not None for p in parts):
            return _or_of([p for p in parts if p is not None])
    return None


def _merge_search_criteria(spec: EffectSpec, extra: Criteria) -> Optional[EffectSpec]:
    """``spec`` (a library search) with ``extra`` ANDed into its criteria, or ``None`` on any collision."""
    if spec.type != "search":
        return None
    criteria = spec.params.get("criteria")
    if isinstance(criteria, str):
        criteria = {"type": criteria} if criteria else {}
    if not isinstance(criteria, dict):
        return None
    if set(criteria) & set(extra):
        return None  # a key written twice would be one of the two filters silently overwritten
    # RULE 701.19a: the searched pool is narrowed, never widened; "or" lists are each ANDed with the rest.
    return EffectSpec(spec.type, {**spec.params, "criteria": {**criteria, **extra}}, condition=spec.condition)


#: Spec type -> how a peeled quality is merged into it. A type absent here has no engine reader for the
#: quality, so the peel declines (the card stays UNMODELED rather than losing the filter).
_CARRIERS: dict[str, Callable[[EffectSpec, Criteria], Optional[EffectSpec]]] = {
    "search": _merge_search_criteria,
}


def peel_filter_slots(clause: str, match_shorter: Callable[[str], Optional[list[EffectSpec]]]) -> Optional[list[EffectSpec]]:
    """The specs of ``clause`` read without its "with <quality>" and with the quality carried, or ``None``."""
    m = _QUALITY_IN_NOUN_RE.fullmatch(clause.strip())
    if m is None:
        return None
    extra = quality_criteria(m.group("quality"))
    if extra is None:
        return None
    shorter = f"{m.group('head')}{m.group('tail')}"
    if " with " in shorter.split(",", 1)[0]:
        return None  # a second qualifier in the same noun phrase: one peel at a time, never half-read
    specs = match_shorter(shorter)
    if not specs:
        return None
    # The quality belongs to the searched card, so exactly one spec may carry it.
    carriers = [i for i, spec in enumerate(specs) if spec.type in _CARRIERS]
    if len(carriers) != 1:
        return None
    index = carriers[0]
    merged = _CARRIERS[specs[index].type](specs[index], extra)
    if merged is None:
        return None
    return [merged if i == index else spec for i, spec in enumerate(specs)]

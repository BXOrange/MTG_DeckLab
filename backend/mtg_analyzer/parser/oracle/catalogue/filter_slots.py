"""Filter-slot peeler (PAR-281): offer "with <quality>" to rows that already own the noun phrase.

A row's regex names the *operation* ("search your library for <criteria>, reveal it, put it into your
hand, then shuffle"); each row spells its own filter vocabulary, so a quality the row never wrote
("... a creature card **with defender** ...") leaves the whole clause unclaimed although the rest is
known-good. This is one ordered step that runs after every row declined (`handlers.match_clause`):

1. cut the single "with <quality>" out of the clause's noun phrase,
2. let the ordinary table claim the shorter clause, and
3. carry the cut quality into the spec the table produced -- as a param the engine already reads.

Each slot (`_SLOTS`) names one filter position, its vocabulary, and the spec types that own an engine
reader for it: the library search's ``criteria`` (`models.cards.card_query`'s vocabulary, checked by the
predicate the search already uses), the entry counters of a return to the battlefield (``extra_counters``,
RULE 614.1c), and the source filter of a targeted stack ability (``source_filter`` -> `TargetSpec.
stack_source_filter`, RULE 113.7a).

Fail-closed: the peel is accepted only when a *carrier* for the produced spec exists. A quality that no carrier can express, a spec
the carrier does not know, a key collision, or a second "with" in the noun phrase all refuse -- the
quality is never dropped (a dropped filter would be a wrong-but-MODELED card).

RULE 701.19a: a search finds only cards that have the quality named. RULE 202.3: mana value. RULE
208/209 (power, toughness) are the printed values of a card outside the battlefield.

Pure regex + data -- no ``game/`` imports (security boundary).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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


def _with_param(spec: EffectSpec, key: str, value: Any) -> Optional[EffectSpec]:
    """``spec`` with one more param, or ``None`` when ``key`` is already set (never overwrite a filter)."""
    if key in spec.params:
        return None
    return EffectSpec(spec.type, {**spec.params, key: value}, condition=spec.condition)


# --- slot: "with <quality>" in a library search's noun phrase -------------------------------------------------
#: The quality sits in the first comma-free segment, which is the noun phrase ("search your library for a
#: creature card with defender" -- the next comma starts the "reveal it, put it ..." tail).
_SEARCH_QUALITY_RE = re.compile(
    r"(?P<pre>.*?search your library for [^,:]*?) with (?P<quality>[^,:]+?)(?P<post>,.*|\.?)",
    re.DOTALL,
)


def _search_quality(m: re.Match[str]) -> Optional[Criteria]:
    if " with " in f"{m.group('pre')}{m.group('post')}".split(",", 1)[0]:
        return None  # a second qualifier in the same noun phrase: one peel at a time, never half-read
    return quality_criteria(m.group("quality"))


# --- slot: "with <N> <kind> counter(s) on it" after a return to the battlefield ------------------------------
#: "return it to the battlefield under its owner's control with a finality counter on it" (Thunderbolts
#: Conspiracy), "... from your graveyard to the battlefield with a mannequin counter on it" (Makeshift
#: Mannequin). One counter kind only, and a P/T counter only as +1/+1 or -1/-1 (the engine's two): "a hexproof counter and an indestructible counter" and "an additional
#: -1/-1 counter" do not match, so they stay unclaimed.
_COUNTER_AMOUNT_WORDS = {"a": 1, "an": 1}
_COUNTER_KIND = r"(?:[+-]1/[+-]1|[a-z]+)"
_COUNTER_PHRASE = rf"(?:an?|\d+) (?:additional )?{_COUNTER_KIND} counters?"
_ENTRY_COUNTERS_RE = re.compile(
    rf"(?P<pre>.*?(?:to|onto) the battlefield[^,]*?) with (?P<counters>{_COUNTER_PHRASE}(?: and {_COUNTER_PHRASE})?) "
    r"on (?:it|them|him|her)(?P<post>.*)",
    re.DOTALL,
)
_ONE_COUNTER_RE = re.compile(rf"(?P<amount>an?|\d+) (?:additional )?(?P<kind>{_COUNTER_KIND}) counters?")
#: The counter-kind words that are not a counter name at all (a keyword counter is a name, "additional" is not).
_NOT_A_COUNTER_KIND = frozenset({"additional", "another", "the", "that", "those", "its", "their"})


def _entry_counters(m: re.Match[str]) -> Optional[dict[str, Any]]:
    if " with " in m.group("pre").split("battlefield", 1)[-1]:
        return None
    # RULE 614.1c / 122.6: "with [an additional] N <kind> counter(s) [and N <kind> counter(s)]" -- the counters are
    # placed as the permanent enters, on top of any it would enter with ("additional" changes nothing here: the
    # return's counters are always additive, `entry_bonus_counters`). Two kinds read as {kind: count, ...}.
    counts: dict[str, int] = {}
    for part in m.group("counters").split(" and "):
        one = _ONE_COUNTER_RE.fullmatch(part)
        if one is None or one.group("kind") in _NOT_A_COUNTER_KIND or one.group("kind") in counts:
            return None
        counts[one.group("kind")] = _COUNTER_AMOUNT_WORDS.get(one.group("amount")) or int(one.group("amount"))
    if len(counts) == 1:
        (kind, count), = counts.items()
        return {"kind": kind, "count": count}
    return counts


def _merge_entry_counters(spec: EffectSpec, counters: dict[str, Any]) -> Optional[EffectSpec]:
    if spec.type == "return_from_graveyard" and spec.params.get("destination", "battlefield") != "battlefield":
        return None
    return _with_param(spec, "extra_counters", counters)


# --- slot: "from <kind> source" on a targeted stack ability --------------------------------------------------
#: "counter target activated ability from an artifact source" (Rust), "copy target activated or triggered
#: ability you control from an artifact or enchantment source" (Weaver of Harmony).
_ABILITY_SOURCE_RE = re.compile(
    r"(?P<pre>(?:counter|copy) target activated(?: or triggered)? ability(?: you control)?) "
    r"from (?:an? )?(?P<source>[a-z]+(?: or [a-z]+)*) source(?P<post>.*)",
    re.DOTALL,
)
_SOURCE_CARD_TYPES = frozenset({"artifact", "enchantment", "creature", "land", "planeswalker"})
_COLORLESS = "colorless"


def _ability_source(m: re.Match[str]) -> Optional[dict[str, Any]]:
    words = m.group("source").split(" or ")
    if words == [_COLORLESS]:
        return {"colorless": True}
    if all(w in _SOURCE_CARD_TYPES for w in words):
        return {"card_types": words}
    return None


# --- slot: "and put <N> <kind> counter(s) on it" after an exile --------------------------------------------
#: "exile up to one target instant or sorcery card from that player's graveyard and put a page counter on it"
#: (Tasha, the Witch Queen): the same rider the `exile_with_counters` row reads as "with a page counter on it",
#: spelled as a second verb. RULE 122.2: the counters go on the new exile object (`ExileControlEffect.exile_counters`).
_EXILE_PUT_COUNTERS_RE = re.compile(
    r"(?P<pre>exile [^,]*?) and put (?P<amount>an?|\d+) (?P<kind>[a-z]+) counters? on (?:it|them)(?P<post>\.?)",
    re.DOTALL,
)


def _exile_put_counters(m: re.Match[str]) -> Optional[dict[str, int]]:
    kind = m.group("kind")
    if kind in _NOT_A_COUNTER_KIND or " and " in m.group("pre"):
        return None  # a second verb in the exile phrase: the "it" is not provably the exiled card
    amount = m.group("amount")
    return {kind: _COUNTER_AMOUNT_WORDS.get(amount) or int(amount)}


def _merge_exile_counters(spec: EffectSpec, counters: dict[str, int]) -> Optional[EffectSpec]:
    return _with_param(spec, "exile_counters", counters)


# --- slot: "with <quality>" in an edict's sacrificed-permanent phrase ---------------------------------------
#: "each opponent sacrifices a creature of their choice with flying" (Clip Wings, Run Afoul) / "target player
#: sacrifices a creature of their choice with mana value 3 or less" (Exile into Darkness) / "each opponent
#: sacrifices a creature with flying of their choice" (Pick Your Poison): the quality narrows the permanents the
#: player may choose (RULE 701.17a), carried as ``SacrificeEffect.object_filter`` (`combat.matches_object_filter`).
_EDICT_QUALITY_AFTER_RE = re.compile(
    r"(?P<pre>.*? sacrifices? (?:a|an|\d+) [a-z ]+? of their choice) with (?P<quality>[^,.:]+?)(?P<post>\.?)",
    re.DOTALL,
)
_EDICT_QUALITY_BEFORE_RE = re.compile(
    r"(?P<pre>.*? sacrifices? (?:a|an|\d+) [a-z ]+?) with (?P<quality>[^,.:]+?)(?P<post> of their choice\.?)",
    re.DOTALL,
)
_MANA_VALUE_BOUND_RE = re.compile(rf"mana value (?P<n>{_NUMBER}) or (?P<cmp>less|greater)")


def _edict_quality(m: re.Match[str]) -> Optional[Criteria]:
    quality = m.group("quality").strip()
    bound = _MANA_VALUE_BOUND_RE.fullmatch(quality)
    if bound:
        return {f"{_BOUND_BY_COMPARATOR[bound.group('cmp')]}_mana_value": int(bound.group("n"))}
    if re.fullmatch(r"[a-z]+", quality):
        return {"keyword": quality} if quality in KEYWORDS else None
    return None


def _merge_edict_filter(spec: EffectSpec, flt: Criteria) -> Optional[EffectSpec]:
    if spec.params.get("greatest") or spec.params.get("greatest_power") or spec.params.get("chooser"):
        return None  # those edicts pick by a ranking / by another chooser; no printed row combines a quality with them
    return _with_param(spec, "object_filter", flt)


# --- slot: "with power or toughness N or less" on a counter-spell's target -------------------------------
_COUNTER_SPELL_STAT_RE = re.compile(
    r"(?P<pre>counter target [a-z ]*?spell) with power or toughness (?P<n>\d+) or less(?P<post>\.?)", re.DOTALL,
)


def _spell_stat_ceiling(m: re.Match[str]) -> Optional[int]:
    return int(m.group("n"))


# --- slot: "with mana value N or less" on a bare target announcement ----------------------------------------
#: "choose target creature with mana value 3 or less" (Expel the Unworthy): the bound narrows the announced target
#: (RULE 601.2c), carried as the announcement's ``creature_filter`` (`combat.matches_object_filter`, the offer-time
#: and resolution-time legality check). Only the battlefield-creature kind has that reader: a graveyard card
#: kind reads no object filter, so "choose target creature card in your graveyard with ..." stays unclaimed.
_CHOOSE_TARGET_MV_RE = re.compile(
    rf"(?P<pre>choose (?:up to one )?target creature) with mana value (?P<n>{_NUMBER}) or (?P<cmp>less|greater)(?P<post>\.?)",
    re.DOTALL,
)
_CHOOSE_TARGET_MV_KINDS = frozenset({"creature"})


def _choose_target_mana_value(m: re.Match[str]) -> Optional[Criteria]:
    return _bounds("mana_value", int(m.group("n")), m.group("cmp"))


def _merge_choose_target_filter(spec: EffectSpec, bound: Criteria) -> Optional[EffectSpec]:
    if set(spec.params.get("kinds") or ()) != _CHOOSE_TARGET_MV_KINDS:
        return None
    existing = spec.params.get("creature_filter") or {}
    if set(existing) & set(bound):
        return None  # never overwrite a bound the row already wrote
    return EffectSpec(spec.type, {**spec.params, "creature_filter": {**existing, **bound}}, condition=spec.condition)


@dataclass(frozen=True)
class _Slot:
    """One peelable filter slot: where it sits, what it means, and which specs have a reader for it."""

    pattern: re.Pattern[str]
    #: The payload the quality means (``None`` = not in this slot's vocabulary -> refuse).
    interpret: Callable[[re.Match[str]], Optional[Any]]
    #: Spec type -> how the payload is merged into that spec. A type absent here has no engine reader for
    #: the quality, so the peel declines (the card stays UNMODELED rather than losing the filter).
    carriers: dict[str, Callable[[EffectSpec, Any], Optional[EffectSpec]]]


_SLOTS: tuple[_Slot, ...] = (
    _Slot(_SEARCH_QUALITY_RE, _search_quality, {"search": _merge_search_criteria}),
    _Slot(_ENTRY_COUNTERS_RE, _entry_counters, {
        "return_from_graveyard": _merge_entry_counters,
        "return_self_to_battlefield": _merge_entry_counters,
    }),
    _Slot(_ABILITY_SOURCE_RE, _ability_source, {
        "counter_ability": lambda spec, flt: _with_param(spec, "source_filter", flt),
        "copy_target_ability": lambda spec, flt: _with_param(spec, "source_filter", flt),
    }),
    _Slot(_COUNTER_SPELL_STAT_RE, _spell_stat_ceiling,
          {"counter": lambda spec, n: _with_param(spec, "max_power_or_toughness", n)}),
    _Slot(_EDICT_QUALITY_AFTER_RE, _edict_quality, {"sacrifice": _merge_edict_filter}),
    _Slot(_EDICT_QUALITY_BEFORE_RE, _edict_quality, {"sacrifice": _merge_edict_filter}),
    _Slot(_CHOOSE_TARGET_MV_RE, _choose_target_mana_value, {"choose_targets": _merge_choose_target_filter}),
    _Slot(_EXILE_PUT_COUNTERS_RE, _exile_put_counters, {"exile": _merge_exile_counters}),
)


def peel_filter_slots(clause: str, match_shorter: Callable[[str], Optional[list[EffectSpec]]]) -> Optional[list[EffectSpec]]:
    """The specs of ``clause`` read without its filter slot and with the slot carried, or ``None``."""
    text = clause.strip()
    for slot in _SLOTS:
        m = slot.pattern.fullmatch(text)
        if m is None:
            continue
        payload = slot.interpret(m)
        if payload is None:
            continue
        specs = match_shorter(f"{m.group('pre')}{m.group('post')}")
        if not specs:
            continue
        # The slot belongs to one operation of the clause, so exactly one spec may carry it.
        carriers = [i for i, spec in enumerate(specs) if spec.type in slot.carriers]
        if len(carriers) != 1:
            continue
        index = carriers[0]
        merged = slot.carriers[specs[index].type](specs[index], payload)
        if merged is None:
            continue
        return [merged if i == index else spec for i, spec in enumerate(specs)]
    return None

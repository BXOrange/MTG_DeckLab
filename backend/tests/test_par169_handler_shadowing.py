"""PAR-169: ``HANDLERS`` order is semantics, so no two rows may claim one real clause with different IR by accident.

Every clause the parser hands the handler table while parsing the whole card cache is offered to every eligible
row. Two rows that both claim it with different IR are a shadowing conflict unless the pair is declared:

* the later row is a declared ``fallback_for`` the earlier one (and really comes after it), or
* the earlier row is context-gated (``self_subject_only`` &c.) and the later one is not: the context-specific
  reading of a pronoun deliberately overrides the default one.
"""
import json
from itertools import groupby

import pytest

from mtg_analyzer.parser.oracle.catalogue import handlers as H
from tests.support.full_cache import READING_FACTS

#: The `ClauseReading` facts an `EffectHandler.requires` can ask for.
_FACTS = READING_FACTS

#: Same-clause/different-IR pairs that are order-dependent by design *beyond* the two declared mechanisms.
#: Empty on purpose: add an entry only with a why-comment, and prefer `fallback_for`.
ALLOWED_CONFLICTS: dict[tuple[str, str], str] = {}


def _gates(handler) -> frozenset[str]:
    return frozenset(f for f in _FACTS if getattr(handler.requires, f))


def _ir(specs) -> str:
    return json.dumps([s.to_dict() for s in specs], sort_keys=True, default=repr)


def _test_handler(name, count, *, requires=None, fallback_for=(), calls=None):
    import re
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import STANDALONE
    from mtg_analyzer.parser.oracle.catalogue.effect_rows.shared import EffectHandler
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    def build(match):
        if calls is not None:
            calls.append(name)
        return [EffectSpec("draw", {"count": count})]

    return EffectHandler(name, re.compile("draw a card"), build,
                         requires=requires or STANDALONE, fallback_for=fallback_for)


def test_conflicts_keep_catalogue_order_fallbacks_and_explicit_allowlist():
    observations = {("draw a card", frozenset())}
    handlers = [_test_handler("first", 1), _test_handler("different", 2),
                _test_handler("same", 1), _test_handler("fallback", 3, fallback_for=("first",))]
    conflicts, examples = _shadowing_conflicts(observations, handlers, {})
    assert conflicts == {("first", "different")}
    assert examples == {("first", "different"): "draw a card"}
    assert _shadowing_conflicts(observations, handlers, {("first", "different"): "intentional"})[0] == set()
    # Reordering changes who wins, and a later row's fallback declaration cannot excuse the new winner.
    assert ("different", "first") in _shadowing_conflicts(observations, handlers[1:] + handlers[:1], {})[0]


def test_context_specific_override_is_directional_and_matches_are_reused_per_clause():
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading

    calls = []
    specific = _test_handler("specific", 1, requires=ClauseReading(self_subject=True), calls=calls)
    generic = _test_handler("generic", 2, calls=calls)
    observations = {("draw a card", frozenset()), ("draw a card", frozenset({"self_subject"})),
                    ("draw a card", frozenset({"self_subject", "attached_subject"}))}
    assert _shadowing_conflicts(observations, [specific, generic], {})[0] == set()
    assert calls.count("specific") == calls.count("generic") == 1
    assert _shadowing_conflicts(observations, [generic, specific], {})[0] == {("generic", "specific")}


def test_two_context_specific_rows_still_report_their_conflict():
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading

    handlers = [_test_handler("self", 1, requires=ClauseReading(self_subject=True)),
                _test_handler("attached", 2, requires=ClauseReading(attached_subject=True))]
    observations = {("draw a card", frozenset({"self_subject", "attached_subject"}))}
    assert _shadowing_conflicts(observations, handlers, {})[0] == {("self", "attached")}


def test_fallback_rows_come_after_their_primary():
    position = {}
    for i, h in enumerate(H.HANDLERS):
        position.setdefault(h.name, []).append(i)
    for i, h in enumerate(H.HANDLERS):
        for primary in h.fallback_for:
            assert primary in position, f"{h.name} is a fallback for unknown row {primary}"
            assert min(position[primary]) < i, f"{h.name} must come after its primary {primary}"


def _shadowing_conflicts(seen, handlers, allowed_conflicts):
    # Eligibility depends only on these recorded facts. Keep catalogue order.
    gates = {id(h): _gates(h) for h in handlers}
    contexts = {on for _, on in seen}
    eligible = {on: tuple(h for h in handlers if gates[id(h)] <= on) for on in contexts}
    conflicts: set[tuple[str, str]] = set()
    examples: dict[tuple[str, str], str] = {}
    ordered = sorted(seen, key=lambda item: (item[0], sorted(item[1])))
    for clause, variants in groupby(ordered, key=lambda item: item[0]):
        # The established shadowing check calls match with its default reading;
        # only eligibility varies across observed contexts. Reuse each result
        # for this clause, without sharing mutable specs or retaining the pool.
        matches = {}
        for _, on in variants:
            claims = []
            for handler in eligible[on]:
                key = id(handler)
                if key not in matches:
                    specs = handler.match(clause)
                    matches[key] = None if specs is None else _ir(specs)
                if matches[key] is not None:
                    claims.append((handler, matches[key]))
            if not claims:
                continue
            first, first_ir = claims[0]
            for handler, ir in claims[1:]:
                if ir == first_ir:
                    continue
                if first.name in handler.fallback_for:
                    continue
                if gates[id(first)] and not gates[id(handler)]:
                    continue
                pair = (first.name, handler.name)
                if pair in allowed_conflicts:
                    continue
                conflicts.add(pair)
                examples.setdefault(pair, clause)
    return conflicts, examples


@pytest.mark.full_cache
@pytest.mark.timeout(900)
def test_no_two_eligible_rows_claim_one_clause_with_different_ir(full_cache_parse):
    assert len(full_cache_parse.clauses) > 10_000, "the full card cache is not loaded"
    conflicts, examples = _shadowing_conflicts(full_cache_parse.clauses, H.HANDLERS, ALLOWED_CONFLICTS)
    assert not conflicts, "undeclared same-clause/different-IR rows (declare fallback_for or retire one):\n" + "\n".join(
        f"  {a} shadows {b}: {examples[(a, b)]!r}" for a, b in sorted(conflicts)
    )

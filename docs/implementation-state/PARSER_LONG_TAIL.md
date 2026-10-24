# Oracle parser: long-tail strategy

Goal: maximize correctly executable supported cards. Standing backlog entry:
PAR-12. Parser recognition alone is not proof of gameplay support.

## Sources of truth

- Open work: [BACKLOG.md](BACKLOG.md), [singletons.md](singletons.md).
- Delivered capabilities: [Done_Backend.md](Done_Backend.md).
- Version history: [PARSER_VERSION_HISTORY.md](../../backend/mtg_analyzer/parser/oracle/PARSER_VERSION_HISTORY.md).
- Permanent exclusions: [DEFERRED.md](DEFERRED.md).
- Implementation workflow: [extend-parser](../../.agents/skills/extend-parser/SKILL.md).
- Architecture: [atom/composition design](../concepts/14_PARSER_GRAMMAR_DESIGN.md).

## Where coverage stands

Measured on 2026-10-24 at PARSER_VERSION 737: **22,168 / 35,051 cards (63.2%)**,
including authored cards; 1,305 permanently unsupported records.
Commander-legal coverage: **21,563 / 32,068 (67.2%)**.
The full-pool probe comparison against v736 reports **9 new supported cards and
zero regressions**, from whole-graveyard shuffles with an announced player target
and the existing each-player wrapper. Source-owner/controller forms retain their
scope; commander choices resume the shared simultaneous departure batch.
The probe's raw pool includes 35,100 card names; the ledger report uses its
authoritative coverage denominator of 35,051.
Measurements use the ledger-backed `scripts/coverage_report.py --top 40`
and its `--commander-legal-only` scope.

## Existing building blocks

These families exist; individual wording, scope and combinations may still fail.
Check their emitted specs and runtime before proposing another primitive.

| Family | Existing examples | Source |
| --- | --- | --- |
| Effects | Draw/discard, damage/life, tokens, destroy/exile/return, search/shuffle | [effect rows](../../backend/mtg_analyzer/parser/oracle/catalogue/effect_rows/) |
| Keywords | Flying, vigilance, trample, deathtouch, lifelink; cost-bearing keywords such as cycling | [keyword grammar](../../backend/mtg_analyzer/parser/oracle/catalogue/keywords.py), [binding](../../backend/mtg_analyzer/game/binding/core.py) |
| Composition | Sequences, optional payment, conditional bodies, delayed and granted abilities | [segmenter](../../backend/mtg_analyzer/parser/oracle/segmenter.py), [composition effects](../../backend/mtg_analyzer/game/effects/composition.py) |
| References | Previous targets, trigger subjects, objects affected “this way” | [binding](../../backend/mtg_analyzer/game/binding/core.py), [targeting](../../backend/mtg_analyzer/game/targeting.py) |
| Conditions/amounts | Conditions, counts, X and “for each” operands | [conditions](../../backend/mtg_analyzer/game/effect_conditions.py), [amounts](../../backend/mtg_analyzer/game/effect_amounts.py) |
| Static abilities | Filters, characteristic changes, hand-size modifiers | [static grammar](../../backend/mtg_analyzer/parser/oracle/catalogue/static_handlers.py), [continuous effects](../../backend/mtg_analyzer/game/continuous.py) |

## Coverage-maximization plan

1. **Freeze input.** Use read-only SQLite backups, isolated test caches and
   source/pool fingerprints. Preserve support exclusions. Report all cached
   cards and Commander separately; never mix card and insert denominators.
2. **Preserve complete blockers.** Catalogue every unresolved line with face,
   ability/block and context. Extract all failing parts, not only one minimal
   deletion span. Keep opaque dependencies; distinguish failed wrappers from
   already-working mode bodies. Repair `rank --by span`, which currently
   computes spans but ranks original lines.
3. **Verify shared capabilities.** Separate grammar, composition/reference,
   binding and engine gaps. Group semantic equivalents, preserving differing
   meanings of identical words. Fragments such as “shuffle” or “if you do”
   often indicate context gaps in existing operations.
4. **Rank complete-card packages.** Record every card's remaining requirements
   and prerequisites. Evaluate singles, pairs/triples and larger shared
   packages by unique complete-card candidates per combined effort/risk.
   Retain zero-SOLO groups: B+C can complete A+B / B+C / C+D's middle card.
   Start with effect-partial cards, then keyword-only and other cards;
   retain the entire supported pool in the objective.
5. **Implement reusable axes.** Extend existing subjects, filters, amounts,
   references and composition first. Deliver missing runtime, binding and
   parser consumers together. Keep fail-closed behavior and security boundaries.
6. **Verify whole cards.** Parse → bind → execute each newly covered structure,
   including nested effects and relevant faces. Test near misses, optional
   choices, changed/illegal targets, reference lifetimes and clone/undo.
   Verify offered actions as well as effect resolution.
7. **Measure and repeat.** Update parser version/history/lock, run the backend
   suite including `--full-cache`, and independently inspect per-card gains
   and losses on unchanged input. Rebuild dependencies after each package.
   Route genuine singletons to hand-authoring after a full-pool comparison.

## Acceptance

- Diagnostic combinations are candidates, not promised gameplay gains.
- Count each physical card once across phrases, packages and faces.
- Keep current-gate coverage, face completeness, binding and behavior evidence
  separate. Keyword recognition and registry membership alone are insufficient.
- Explain every loss; correctness fixes may remove false MODELED claims.
- Zero immediate gain does not exhaust discovery: inspect prerequisites,
  larger packages and opaque contexts.
- Complete supported-pool modeling requires no unresolved supported cards or
  relevant faces, successful binding and passing behavior-family tests.
  Coverage percentages alone do not prove all rules interactions correct.

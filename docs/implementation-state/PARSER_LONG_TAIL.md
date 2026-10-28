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

Measured on 2026-10-28 at PARSER_VERSION 804: **23,753 / 35,051 cards (67.8%)**,
including authored cards; 1,305 permanently unsupported records.
Commander-legal coverage: **23,136 / 32,068 (72.1%)**.
PAR-217 adds characteristic-changing bodies over the shared object phrase,
including layered type/color/base-P/T changes, named forms, quoted grants,
keyword loss and resolution-time choices. Against v799, the complete pool gains
**145 parser-modeled names, zero lost**, with five reviewed existing-spec changes
that retain target restrictions. The v804 Commander scan records **8,812 open
cards and 12,947 fragments**, down from **8,949 and 13,133** at v799. Independent
name-reference, optional-payment and unsupported quoted-body gaps stay distinct
from the delivered characteristic-change grammar.
The paragraphs below record how earlier batches moved the slot counts from v783 on.
PAR-212 extends the shared object-state predicates (counter thresholds, chosen
types, per-player count comparisons and payment-time crew history) and composes
destination wording and exile-counter riders through the existing move effects.
Emerge uses alternative casting with an actual sacrifice and retains its paid
cost and sacrifice characteristics for conditional payoffs. Conditional target
subjects announce once and gate the whole payoff; crew/count intervening-ifs
gate complete triggered bodies. Live crew targets retain exact visits, while
historical counts include departed creatures. The v786 full-pool comparison
against v783 records **66 newly parser-modeled names, zero lost**, and one
reviewed existing-spec correction: Encumbered Reejerey's counter condition gates
triggering as well as resolution. Its zero/one-counter cases execute in the
family tests. Ayara's Oathsworn likewise gates its entire counter/search body.
The ledger gains 58 covered cards because some newly parsed
cards already had authored implementations.
The fresh v786 scan records **13,777 open sentences** (13,854 at v783), **9,241
open Commander cards** (9,298), and **14,247 open atoms** (14,331). Open slots
fall for condition/pronoun **1,403 → 1,348**, put/pronoun **473 → 355**,
hand/pronoun **540 → 423**, battlefield/pronoun **524 → 521**, and
exile/pronoun **478 → 465**. The phrase `if it's a` falls from **110 → 97**
open cards under the same n-gram/ablation measurement. These overlapping counts
measure shared slots; independent inspection leads are delivered in PAR-213.
PAR-211 adds shared quantified player/object sets, contextual controllers,
per-member instructions and player-relative amounts. The full-pool spec diff
against v779 finds **46 newly parser-modeled names, zero lost**, with two
reviewed existing-spec changes: Radiating Lightning uses its announced player's
creatures and Balefire Dragon retains the damaged player and event amount through
the shared selector. Both execute in regression tests; player exclusions, cloned
choices, group identities, fixed durations and combat-only prevention are also
validated through the real engine.
The v783 scan records **13,854 open sentences** (13,917 at v779), **9,298 open
Commander-legal cards** (9,340), and **14,331 open atoms** (14,398). Open slot
counts fall for `obj:creature + obj:eachall` **1,327 → 1,296**,
`obj:eachall + obj:player` **672 → 641**, `obj:eachall + qty:foreach`
**738 → 713**, `obj:eachall + ref:pronoun` **792 → 773**, and
`dur:eot + obj:eachall` **431 → 421**. These overlapping counts measure the
quantifier grammar; conditions/actions still missing from their sentences remain
in later fragment tickets; PAR-212 and PAR-213 supply the shared object-state and
zone-destination and inspection-sequence grammar.
PAR-209 factors target adjectives, fixed durations and quantity spellings into
shared atoms and extends name references and prevention scopes. Against v777,
**83 newly parser-modeled names, zero lost**; 16 existing specs retain their
restrictions through the shared grammar, including both Fight operands.
Same-name cross-zone searches retain the pre-move name/controller, require
public graveyard finds and offer hidden-zone finds through the existing search
continuation. Linked pool hand returns retain exact source/card exile visits.
The v779 re-scan records **13,917 open sentences** (14,027 at v777), **9,340
open Commander-legal cards** (9,419), and **14,398 open atoms** (14,528).
Phrase occurrences on open cards fall from 104 to 87 for `the same name`,
138 to 126 for `base power and toughness`, and 101 to 96 for `exiled with ~`.
These are measured reductions, not a claim that unrelated conditions and
actions on every card containing those phrases are modeled.
PAR-210 adds the shared object-phrase grammar and fail-closed reference binding:
against v772, **431 newly parser-modeled names, zero lost** and 58 changed
existing specs (player actors through comma-then series, created/previous-player
referents). The v777 fragment scan records **14,027 open sentences** (14,593 at
v772) on 9,419 open Commander-legal cards.
PAR-208 adds outcome/else chains, comma-separated effect series, other-player
library searches, typed/random discard costs and untargeted graveyard returns.
Against v771, the full-pool comparison finds **49 new parser-modeled card names,
zero regressions** and six changed existing specs: four equivalent graveyard
selection nodes, plus corrected optional-action scope for Summon Undead and
Gallifrey Stands. All six changed cases execute in regression tests.
The v772 fragment scan records **14,593 open sentences**, including **4,771
follow-ups on 3,589 cards**. Distinct open multi-sentence card/parent pairs fall
from **4,029 at v771 to 3,999** using identical counting; the pre-PAR-208 baseline
was 4,055. Reveal pools and pronoun/state-bound follow-ups were then split across
PAR-211…214: quantifier scopes (PAR-211), object-state/destination grammar (PAR-212),
inspection sequences (PAR-213) and verb rows over the shared object phrase (PAR-214).
**Plan from the v792 scan.** 9,179 open Commander cards hold 13,440 open sentences
in 11,713 distinct templates; the best exact template unlocks 5 cards, and trigger
or cost heads are rarely the blocker (468 head-only failures against 3,678
body failures under a parsed head). The remaining tail is therefore worked as
shared axes over the PAR-210 object phrase, ranked by open cards touched / cards
whose every open sentence carries the axis: referenced-object amounts and
mana-value comparisons (PAR-215), prevention/redirection (PAR-216),
type-changing "becomes" (PAR-217), combat requirements (PAR-218), name references
(PAR-219), linked exile and cast windows (PAR-220), control change and counter
movement (PAR-221), per-player trigger scopes (PAR-222), condition-bound and
next-turn durations (PAR-223) and small rows for existing effects (PAR-224).
Graveyard/library play windows are the one verified missing engine primitive
(MEC-135); the colour-conditional counter target filter is a correctness bug
(BUG-37). Axis counts overlap, so re-scan after each ticket and re-rank; cards
left with a single unshared sentence go to `singletons.md` for hand-authoring.
The probe's raw pool includes 35,100 card names; the ledger report uses its
authoritative coverage denominator of 35,051.
Measurements use the ledger-backed `scripts/coverage_report.py` and its
`--commander-legal-only` scope; tests use isolated card/raw databases.

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

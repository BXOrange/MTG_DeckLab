# 13 — Oracle parser: a structural review of granularity and composition

**Status:** assessment, 2026-09-08, against PARSER_VERSION 298.
**Reviews:** [09_ORACLE_EFFECT_PARSER.md](09_ORACLE_EFFECT_PARSER.md) (design intent).
**Changes no code.** The recommendation in §7 is a proposal, not a shipped plan.

**Update, 2026-09-16:** §3.2/§6's "the IR has no composition nodes" is no
longer accurate — [14_PARSER_GRAMMAR_DESIGN.md](14_PARSER_GRAMMAR_DESIGN.md)'s
S0–S3 shipped since this review was written (ENG-34…ENG-37: the atom
inventory, a general continuation/suspension primitive, one structured
condition vocabulary, and composite IR nodes + fusion retirement —
`game/isa.py`, `game/continuations.py`, `game/effect_conditions.py`,
`game/effects/composition.py`). What remains open, confirmed still live in
today's code, is specifically §3.1/§3.3's `fullmatch`-only handler dispatch
and all-or-nothing connector split, and §3.4's cross-module slot-grammar
reuse gap — tracked as **PAR-115** and **PAR-116** in
[BACKLOG.md](../implementation-state/BACKLOG.md). The measured evidence in
§5 below stays a frozen PARSER_VERSION 298 snapshot; don't cite its exact
numbers as current.

The question this answers: *is the parser's handler granularity right, or is it
over-specific — and does the grammar understand chaining and branching of
effects on its own?*

Short answer, in two parts.

**Yes, it is over-specific, and the granularity is a symptom rather than the
disease.** The parser is a whole-clause lookup table rather than a grammar, and
its IR has no node for sequencing, branching, iteration, or variable binding.
Because a combination of two already-known effects cannot be *derived*, it has
to be *memorized* — so handler rows multiply along every axis the shared
sub-grammars failed to capture. There are now **22,753 distinct unclaimed
templates for 20,328 blocked cards** (§5.1).

**And the operation vocabulary underneath is closed and small.** Decomposed into
atoms, the entire unclaimed corpus draws on **130 distinct operations, of which
the top 50 cover 94.9%** — against 21,194 distinct whole-clause skeletons that
are 93.1% singletons even after abstracting every slot a grammar would have
(§5.6). **The explosion is combinatorial, not lexical.** The parser is
enumerating arrangements of a small closed alphabet, which is precisely the
condition under which a compositional grammar pays and a lookup table does not.

One measurement in §5.6 must not be read alone: *holding the atom inventory
fixed at what the handler table claims today*, solving composition would flip
only 5.3% of blocked cards. That is the marginal value of one factor in a
program whose payoff is multiplicative — it bounds "composition retrofitted onto
today's atoms", not "an atom inventory plus a composition layer". An earlier
draft of this review drew the wrong conclusion from it.

Readers should also see §4.1: a prior review (`81c3320`) prototyped and rejected
an *adjacent* proposal — a clause-tier aimed at cutting handler count by
absorbing surface phrasing — and that conclusion is stranded on an unmerged
branch. §5.6(b) is a different claim and is not refuted by it.

---

## 1. Scope and method

Examined: everything under `backend/mtg_analyzer/parser/oracle/` (29,764
lines), its IR consumers (`game/effect_binder.py`, `game/effects/core.py`,
`game/ability_catalogue/`, `game/targeting.py`, `game/static_conditions.py`),
and the coverage ledger `backend/data/coverage.db`.

Every number below was re-derived read-only during the review.

**Bucket segmentation of the Commander-legal remainder** (~4 min). Note two
environment requirements: `PYTHONIOENCODING=utf-8` is mandatory (the script's
box-drawing output crashes on a cp1252 console), and the venv interpreter is
required — `httpx2` is a real pinned dependency, absent from system Python.

```bash
cd backend
PYTHONIOENCODING=utf-8 ./venv_win/Scripts/python.exe \
    scripts/commander_tail_report.py --min-cluster 5 --samples 3 --top-b 25
```

**Coverage-ledger figures** (§5.1) — verdict counts, clause and template
distribution — come from this read-only query; save it to a scratch file and run
it with the same interpreter:

```python
import sqlite3, json, sys
sys.path.insert(0, ".")
from collections import Counter
from mtg_analyzer.services.coverage_db import DEFAULT_COVERAGE_DB_PATH as P
from mtg_analyzer.parser.oracle import abstract_clause

db = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
for r in db.execute("SELECT coverage,source,COUNT(*) FROM card_coverage "
                    "WHERE parser_version='298' GROUP BY 1,2 ORDER BY 3 DESC"):
    print(r)

rows = db.execute("SELECT unclaimed FROM card_coverage WHERE parser_version='298'"
                  " AND coverage='unmodeled' AND source='parser'").fetchall()
per, tmpl, total = Counter(), Counter(), 0
for (u,) in rows:
    clauses = json.loads(u or "[]")
    per[min(len(clauses), 5)] += 1
    total += len(clauses)
    for c in clauses:
        tmpl[abstract_clause(c)] += 1
print(f"cards={len(rows)} clauses={total} templates={len(tmpl)}")
print("clauses per card:", dict(sorted(per.items())))
```

The §5.2 marker table is the same clause list counted against a regex per
marker. Structural counts (`len(HANDLERS)`,
`len(spec._ALLOWED_CONDITION_KEYS)`, …) were read at runtime rather than by
grepping source, so they reflect what actually loads.

---

## 2. The structure as built

`09_` describes the intended pipeline. This is the shape it has today.

**Splitting happens at three levels, and the top level is not sentences.**

1. **Newline** (`gate.py`) — one printed line = one ability. This is the unit
   the coverage gate accounts for. Multi-line block structures (Leveler, Class,
   Station, modal, Spree, Saga) are peeled first by dedicated splitters.
2. **Wrapper peel** (`segmenter.segment_line`, a 1,600-line function with 129
   return sites) — strips the trigger phrase, the activation cost, and a
   *leading* `you may`.
3. **Connector split** (`segmenter.parse_effect_body`) — and only *after* the
   whole body has failed to match as one clause.

**Handler dispatch is an ordered regex list.** `HANDLERS` is a flat
`list[EffectHandler]` of **394 rows**; `match_clause` scans it linearly and the
first row to claim the clause wins. Row order is semantically load-bearing (a
specific row must precede the general row it is a superset of) and is
maintained by comments, not by any constraint the code can check.

The other three surfaces are not registries at all: `static_effect_specs` is a
~900-line if-chain, `replacement_clause_specs` the same shape, and
`segment_line` as above.

| File | lines |
| --- | --- |
| `catalogue/handlers.py` | 12,168 |
| `segmenter.py` | 5,332 |
| `catalogue/static_handlers.py` | 3,943 |
| `gate.py` | 3,505 (of which ~2,580 are a contiguous PARSER_VERSION changelog comment) |
| `spec.py` | 1,246 |
| `catalogue/subgrammars.py` | 601 |

---

## 3. Diagnosis

### 3.1 One regex must claim an entire clause

`EffectHandler.match` is:

```python
m = self.regex.fullmatch(clause.strip())
return self.build(m) if m is not None else None
```

**`fullmatch`, not `search`.** There is no partial claim and no residue
mechanism — a handler cannot consume the first half of a clause and hand the
rest on. This is what makes the coverage gate fail-closed, and it is also what
makes composition undiscoverable: *a clause combining two known effects matches
no row, so it needs a row of its own.*

### 3.2 The IR has no composition nodes

`AbilitySpec.effects` is a flat `list[EffectSpec]`, and `EffectSpec` is exactly
`{type, params, condition}`. Its own docstring states the ceiling:

> "A whitelisted shape (`_ALLOWED_CONDITION_KEYS`), not an arbitrary predicate —
> it can only gate whether an already-whitelisted effect applies, **never choose
> *which* effect runs**."

What that costs, construct by construct:

| Construct | How it is represented today |
| --- | --- |
| **Sequencing** | List concatenation. The segmenter's own comment calls "then" *"sequencing, not effect grammar"* — the ordering carries no semantics. |
| **Conditionals** | A `condition` dict stamped onto *every leaf* of the branch. A decoration, not a node. |
| **If / else** | Two sibling effects with complementary conditions. Nothing enforces that they stay complementary. |
| **`otherwise`** | Grammar exists for **two cards** (one clash form, one verbatim single-card sentence). |
| **`instead`** | Explicitly declined. `replacements.py`: RULE 616.1's full grammar is *"deliberately not attempted exhaustively here"*; `segmenter.py` separately refuses the effect-body amount-override shape. |
| **`you may`** | A *positional* boolean, stripped only at the head of a body. Mid-body is a known standing gap, named as such in `09_`. |
| **`for each`** | An amount fragment, never an iteration operator. There is no `for_each` spec type. |
| **`up to N`** | Pinned at N=1 (`UP_TO_ONE`), with a comment declining the general case as *"a materially larger feature this grammar doesn't attempt"*. |
| **Variable binding** (`where X is …`) | No construct at all. |
| **Data flow between steps** | Not in the IR — eight dynamically-scoped `GameContext` registers (`previous_targets`, `created_objects`, `clash_won`, `life_lost_this_way`, …), each added for one card family. |

There is **no general `if <predicate>, <effect>` rule.** `parse_effect_body`
opens with a cascade of **26 hand-coded prefix-peelers**, each matching one
phrasing, recursing on the remainder, and stamping one fixed key from a
**43-key whitelist**. Adding a predicate costs four coordinated edits: a regex,
a cascade branch, a `_ALLOWED_CONDITION_KEYS` entry, and an engine branch in
`ConditionalEffect._condition_holds`.

The whitelist itself shows the strain. `no_spells_cast_last_turn` and
`two_or_more_spells_cast_last_turn` are two keys for **one quantity at two
thresholds**; `cards_in_graveyard_at_least`,
`instant_sorcery_cards_in_graveyard_at_least` and `graveyard_has_type` are
three keys for one zone predicate; `source_has_subtype` and
`previous_target_has_subtype` are one predicate against two subjects.

### 3.3 Composition is a fallback, and all-or-nothing

`parse_effect_body` tries `match_clause` on the **whole body first**, and only
on failure splits on four separators:

```python
_CONNECTORS: tuple[str, ...] = (r"\.\s+", r";\s+", r",?\s+then\s+", r"\s+and\s+")
```

Each part is parsed independently and the results concatenated — but if **any**
part fails, the entire body is abandoned (`ok = False; break`). So one
unmodelable fragment discards the parse of every sibling that *did* work.

The only cross-clause state is four hand-threaded booleans (`self_subject`,
`previous_subject`, `group_subject`, `previous_selector`) whose bookkeeping runs
~50 lines of accreted special cases — clash is "referent-transparent", a clause
that *consumed* the pronoun re-arms the chain, a new target breaks the
self-carry. This is a hand-rolled substitute for a referent environment.

The same all-or-nothing blast radius applies to modal blocks: when one mode body
fails, `gate.py` appends the header **and every sibling body** to `unclaimed`.

### 3.4 Sub-grammars were factored on exactly one axis

`09_` sets the rule: *"one damage handler with a shared target sub-grammar, not
three regexes… without this factoring the regex set blows up combinatorially."*
It held for `TARGET` (114 uses) and essentially nowhere else.

- **`_SUBJECT` exists and is used 5 times.** Meanwhile the same 5–7-way subject
  alternation is re-spelled per verb family: `_FIGHT_*` (5 rows),
  `_POWER_DAMAGE_*` (7), `_PUMP_*` (6), `_PHASE_OUT_*` (4), `_ANTHEM_*` (4),
  `_SKIP_UNTAP_*` (3), `_GRANT_PROT_CHOICE_*` (3)… The decision is explicit in
  `handlers.py`: *"only the repetitive `EffectHandler(...)` registration itself
  is factored into this row table, **not the regexes/builders behind it**."*
- **`TARGET` is a flat enumeration of 38 noun phrases**, not
  type × controller-scope × qualifier. So a qualifier has to be bolted onto each
  verb separately — the two-colour filter is duplicated **eight times**, once
  per verb, with the reason stated twice in comments: *"the shared `TARGET`
  macro carries no colour slot, so a dedicated row."*
- **`PERMANENT_TYPE_WORD` has zero uses**, despite a docstring describing the
  duplication it was written to remove. The same five-entry colour dict is
  declared **three times**. *(PAR-63: the colour dict was actually declared
  **eight** times; unified as `subgrammars.COLOR_LETTERS`. `PERMANENT_TYPE_WORD`
  became `CARD_TYPE_WORD_ALT` — the five printed card types — and is now shared
  by two rows; no site ever wanted the abstract "permanent"/"nonland permanent"
  readings the old join carried.)*
- **Reuse across modules is near zero.** `static_handlers.py` (3,943 lines)
  imports five names from `subgrammars` and not `TARGET`; `replacements.py`
  imports none. Both roll their own subject and scope grammar. *(PAR-63:
  `replacements.py` now imports `COLOR_LETTERS`. `static_handlers` not importing
  `TARGET` was measured and is **correct** — its target-adjacent grammar
  matches a spell's chosen targets against criteria, `TARGET`'s maps a phrase
  to an engine `target_kind`; different jobs, statics take no targets.)*
- **Effect *pairs* are written out longhand.** Five near-identical handlers
  cover pairs drawn from {draw, gain_life, lose_life} sharing one
  `{DEVOTION}`-scaled X. The comment above them explains why they cannot be
  split: the shared "where X is …" binding has no scope construct that would
  survive the connector split. **The missing feature is described in a comment
  and worked around by enumeration.**

### 3.5 In fairness: no card-name hacks

A full scan found **zero card-name string literals in executable code and zero
name-equality dispatch** anywhere in the parser. Self-reference folding is
derived from the card's own `name`, not enumerated. The ~50 card names in
`handlers.py`/`segmenter.py` are all in comments documenting which real card
motivated a row.

The over-specificity is by **phrasing**, not by identity: dozens of regexes
match one printed card's sentence verbatim. That is a meaningfully better
failure mode — it degrades gracefully and never lies about a card — but it does
not generalize, and a card that swapped two clause bodies is a new shape.

---

## 4. What the project already knew

This review's contribution is quantification and a structural proposal. **The
qualitative diagnosis is already in the repo**, in `09_`'s own sub-grammar
section:

> "**This rule is aspirational more often than it should be.** … most handlers
> in `catalogue/handlers.py` still hand-roll their own type-word lists,
> zone-name alternations, and number-matching inline, **because it's locally
> faster to write one more regex than to go generalize a shared one under
> batch-yield pressure. That debt is exactly what makes the parser brittle to
> "English is hard" instead of robust to it** — the same phrasing gotcha bites
> multiple handlers independently instead of being fixed once."

`PARSER_LONG_TAIL.md` records the symptom repeatedly — *"the easy big wins are
genuinely thinning out"*; a whole top-N ranking that turned out already claimed,
every card blocked instead by a distinct one-off co-resident clause; *"the gains
that matter are almost always in shared grammar."*

**But no document and no open ticket on this branch proposes a grammar or IR
restructuring.** The remedy on offer is always "one more narrow row, or
hand-author."

### 4.1 A prior review already rejected an adjacent proposal — and its conclusion is stranded

Commit **`81c3320` (2026-08-27), "Tier C: prototype a clause-tree grammar tier,
find it doesn't pay off here"**, evaluated a *shallow subject/verb/object clause
parser* between `normalize()` and the handler table, aimed at cutting handler
count by absorbing surface-phrasing variation. It investigated the
damage/destroy/exile family (43 of 237 rows at the time) before writing any
grammar code and concluded:

> "most of it is **not** surface-phrasing redundancy — `damage_kicked_override`/
> `damage_each_multi_target`/`divided_damage`/`damage_selector_devotion`/… are
> genuinely distinct effect shapes that would each still need their own semantic
> mapper under a clause-tree architecture, not fewer."

with a standing instruction: re-attempt **"only with a fresh, concrete count of
*that* family's own genuinely-duplicated vs. genuinely-distinct rows."**

**That commit is not an ancestor of `Commander-Legal-Trail`.** It lives on
`arch/grammar-tier-prototype`, so neither its 44-line conclusion section in
`09_` nor its `subgrammars.SELF_SUBJECT_PREFIX` fix is present on the working
branch — which is why the first draft of this review did not account for it.
**That section should be merged or cherry-picked**; a recorded architectural
negative result invisible on the branch people work from will keep being
re-proposed.

Two things must be said about how it bears on this review. It tested a
*different claim* — surface-phrasing variation measured against **handler
count**, in one family — where this review's claim is composition constructs
measured against **coverage**. And its own list of "genuinely distinct effect
shapes" is revealing: a *kicked override* is a conditional branch, a
*selector-scaled mass effect* is a variable binding. Those are distinct shapes
**because** the IR cannot express the construct (§3.2), which is this review's
point seen from the other side.

But its warning stands, and §5.6 shows it substantially generalizes.

---

## 5. Measured evidence

### 5.1 The headline: more templates than blocked cards

`coverage.db` at PARSER_VERSION 298:

| verdict / source | cards |
| --- | --- |
| modeled / parser | 13,612 |
| modeled / authored | 77 |
| unmodeled / authored | 868 |
| **unmodeled / parser** | **20,328** |
| never_supported / parser | 64 |

Those 20,328 blocked cards carry **25,896 unclaimed clauses**, which abstract
(via the parser's own `abstract_clause`) to **22,753 distinct templates** —
**1.12 templates per blocked card.**

`processing_list.py` states the design target explicitly: *"The unit of the
backlog is the template, not the card (docs/09: a few hundred templates, not
tens of thousands of cards)."* **That ratio has inverted.** Templates blocking
exactly one card account for **82.2%** of all clause incidences:

| template blocks | clause incidences | share |
| --- | --- | --- |
| exactly 1 card | 21,294 | 82.2% |
| 2 | 1,898 | 7.3% |
| 3–4 | 1,131 | 4.4% |
| 5–9 | 811 | 3.1% |
| 10–19 | 281 | 1.1% |
| 20+ | 481 | 1.9% |

And **80.0% of blocked cards fail on exactly one clause** (16,266 of 20,328) —
14.7% on two, 3.7% on three, 1.6% on four or more. The typical loss is a card
whose text the parser almost entirely understands.

For scale: v110 → v298, **188 version bumps, bought +6.0 coverage points.**

### 5.2 Composition connectives are present throughout the remainder

*(Present, but see §5.6 — presence is not the same as being the blocker.)*

Across all 25,896 unclaimed clauses:

| marker | clauses | share |
| --- | --- | --- |
| `if <cond>` | 4,278 | 16.5% |
| `you may` | 3,580 | 13.8% |
| `then` | 2,145 | 8.3% |
| `for each` | 1,525 | 5.9% |
| nested/delayed trigger | 1,524 | 5.9% |
| `equal to` | 1,468 | 5.7% |
| quoted ability | 1,110 | 4.3% |
| `up to` | 1,037 | 4.0% |
| `instead` | 881 | 3.4% |
| `as long as` | 855 | 3.3% |
| `that many` / `that much` | 522 | 2.0% |
| `unless` | 435 | 1.7% |
| `otherwise` | 162 | 0.6% |
| `rather than` | 125 | 0.5% |
| **any of {if, then, instead, you may, for each, unless, otherwise, rather than}** | **9,661** | **37.3%** |

An independent check on a different denominator — ~4,000 Commander-legal cards,
unclaimed *abilities* with trigger and cost wrappers peeled — put at least one
connective in **48.3%** of them, and found the most frequent non-parsing
fragments to be glue rather than exotic effects: `if you do`, `when you do`,
`otherwise`, `exile it instead`, `you may pay {N}`.

### 5.3 The "bespoke tail" is partly a classification artifact

`scripts/commander_tail_report.py` segments the Commander-legal remainder by
cause:

| bucket | meaning | cards |
| --- | --- | --- |
| A | block-wrapper / re-measure | 9 |
| B | recurring template → `PAR-*` | 761 |
| C | set-specific mechanic → `PAR-*` | 224 |
| D | primitive-blocked → `MEC-*` | 132 |
| **E** | **bespoke tail → hand-authoring** | **16,708** |
| F | never-supported (out of denominator) | 47 |

**93.7% of the gap lands in "bespoke."** But bucket E is defined as *"only rare
templates, no primitive gap, no near-miss handler"* — and rarity is measured on
the *whole-clause* template. Under whole-clause templating, any novel
arrangement of familiar atoms is a unique template with N=1. The bucket's actual
members bear this out:

- **A Tale for the Ages** — "enchanted creatures you control get +N/+N." (an anthem)
- **Aang's Defense** — "target blocking creature you control gets +N/+N until end of turn." (pump; only the target filter is unfamiliar)
- **Abiding Grace** — "return target creature card with mana value N from your graveyard to the battlefield." (reanimate; only the filter is unfamiliar)
- **A Little Chat** — "look at the top N cards of your library. put N of them into your hand and the other on the bottom of your library."

None of these needs a new primitive. Each needs one slot the grammar cannot
fill, or one connective it cannot represent.

### 5.4 Cards lost to a single connector

Sampled from the single-unclaimed-clause majority — in each case a chunk of the
sentence already has working grammar and the card is lost anyway:

| card | what claims | what doesn't |
| --- | --- | --- |
| **Prying Questions** | the drain | "puts a card from their hand on top of their library" |
| **Corpsehatch**, **Grave Birthing** | destroy + token creation | the quoted-ability grant on a `previous_selector` referent |
| **Warhost's Frenzy** | the pump | `if this spell was kicked, <delayed **triggered ability**>` — the kicked peeler wraps effects, not triggers |
| **Apprentice Necromancer** | reanimate + haste | "at the beginning of the next end step, sacrifice it" — a delayed trigger inside a body has no representation |
| **Inverted Iceberg** | "draw a card" | "mill a card" inside the same trigger wrapper |
| **Nimrodel Watcher** | — | "and" chaining a pump with a combat restriction; the pair doesn't claim |

### 5.5 A caution on the top-templates ranking

Modal wrapper headers dominate the live top-40 ranking (`choose <n> —` alone at
206). That is largely an artifact of §3.3's block fail-close, which blames every
sibling body when one fails.

**But it is not a cheap win, and the ranking should not be read as one.** Of the
**402** blocked cards whose only non-bullet unclaimed clauses are modal headers,
only **20** have every mode body already parsing via `parse_effect_body`; for
the rest the bodies genuinely fail too. Those 20 are mostly *activated* and
*triggered* modal headers (`{cost}: choose 1 —`), a different shape from the
bare spell header the block splitter handles.

This is a concrete instance of `PARSER_LONG_TAIL.md`'s own standing lesson —
*"a ranked template that is a block wrapper is usually a red herring… re-derive
which sub-clause actually fails before trusting a template's face-value card
count."*

### 5.6 Composition alone is a minority lever — but that is the wrong measurement

Two measurements are needed here, and conflating them produces the wrong
conclusion. This section records both, because the first one alone is
misleading.

**(a) Composition with the atom inventory held fixed.** For every UNMODELED
card, peel the composition wrappers the IR cannot express (leading
`if <cond>,` / `you may` / `then`; trailing `where X is …` / `unless …`), split
on the connectives, and test whether *every* resulting atom already parses via
`parse_effect_body`:

| | cards |
| --- | --- |
| UNMODELED cards examined | 20,328 |
| …whose every clause reduces to **already-claimable** atoms | 1,070 (5.3%) |

Even that is generous — peeling a guard discards meaning a real grammar must
re-attach, and inspecting the 1,070 shows many are actually blocked by
trigger-condition vocabulary rather than composition.

**This number is real but it does not bound the program**, because it holds the
atom inventory at exactly what the handler table claims today. It measures the
marginal value of adding composition while pinning the other factor — and the
payoff of "atoms × composition" is multiplicative, not additive.

**(b) Is the atom inventory bounded?** This is the question that matters, and
the answer is emphatically yes. Decomposing the 24,352 unclaimed clauses on
connectives yields 62,144 atoms. Against a **149-word operation vocabulary
hand-listed from the Comprehensive Rules — RULE 701 keyword actions plus the
ordinary effect verbs — written without looking at the corpus**:

| | |
| --- | --- |
| atoms invoking a verb from that inventory | **70.7%** |
| distinct verbs actually occurring | **130** |
| top 10 verbs | 47.1% of covered atoms |
| top 25 | 77.4% |
| **top 50** | **94.9%** |
| top 75 | 99.2% |

Set that against the same corpus measured at the **clause** level, abstracting
every slot a real grammar would have (targets, types, zones, players, colours,
durations, counters, keywords, mana, numbers):

| unit | distinct | occurring once | concentration |
| --- | --- | --- | --- |
| whole clauses, slot-abstracted | 21,194 | 93.1% | top 5,000 → 33.5% of mass |
| **atoms, by operation** | **130** | 1.5% of mass | **top 50 → 94.9%** |

Slot-abstraction at the clause level collapses almost nothing (21,465 → 21,194,
98.7%). At the atom level the distribution has a steep head and a negligible
tail. **The explosion is combinatorial, not lexical.** The parser is enumerating
combinations of a closed, ~130-element operation set — which is exactly the
condition under which a compositional grammar pays and an enumerated table does
not.

That reframes §5.3's "bespoke tail" too: those 16,708 cards are not 16,708
distinct behaviours, they are arrangements drawn from a small alphabet.


## 6. What the engine already supports

This is what makes the recommendation cheap rather than speculative.

`game/effects/core.py` registers **457 effect types** (plus 17 replacement
families), and **the composition machinery already exists there**:

- `PayCostThenEffect` — real if/else, via `effects` + `else_effects`, plus a
  `then_trigger` variant that goes on the stack with full RULE 115 target
  selection.
- `RepeatProcessEffect` — a loop (one hardcoded predicate, capped at 20).
- `CreateDelayedTriggerEffect`, `ChooseObjectsEffect.then`, vote
  `winner_specs`/`majority_specs`, `each_player_pay_or`,
  `all_players_decline_or` — all take nested effect lists.

All of them build their nested specs at resolve time through `build_effects`, so
**the `type` whitelist still gates every depth.** The engine records the gap
from its own side, in `LivingWeaponEffect`'s docstring: *"there's no vocabulary
for whatever the previous effect just made — an atomic effect class per verb
pair was the only alternative."* That is why a large share of the 457 types are
one-card verb-pair fusions.

**What is missing is a typed node in the IR, not engine capability.**

Two further assets:

- **`game/static_conditions.py` is the better-designed condition vocabulary** —
  48 kinds, a real `"all"` combinator, and `CONDITION_SUBJECTS = {"source",
  "attached", "affected"}`: an explicit `of` key naming *which object* the
  condition reads, instead of baking the subject into the key name. **The
  precedent for reusing it already exists in-tree**: `effect_binder.py` imports
  its `condition_holds` and uses it to wrap every replacement in a generic
  `active_if` gate, rather than each factory reimplementing its own.
- **Validation stops at depth 0.** Nested `params["effects"]` bypass
  `_clamp_params` and `_validate_condition`, so `MAX_EFFECT_MAGNITUDE` is not
  enforced below the top level, and a nested `condition` is silently dropped
  rather than rejected. The hard security boundary (the `type` whitelist) does
  hold at every depth. Promoting nesting into the schema would close the
  clamping gap as a side effect.

---

## 7. Recommendation

> The design that follows from this section — the machine model, the four-axis
> decomposition, and the staged plan with its dependencies — is written up
> separately in
> [14_PARSER_GRAMMAR_DESIGN.md](14_PARSER_GRAMMAR_DESIGN.md). **That document
> supersedes the stage list below**, notably by inserting a continuation-
> unification stage ahead of the composite IR nodes: 97 of `RulesEngine`'s 254
> public methods are `request_*`/`resolve_*_choice` pairs, and
> `deferred_effects` parks a flat list by position, so `optional`/`for_each`
> cannot suspend correctly until that is structure-aware.

**Build the atom layer first, then compose over it.** The sequencing matters:
retrofitting composition onto today's handler-claimed atoms is the 5.3% case in
§5.6(a). Deriving an explicit, complete atom inventory and *then* giving it
composition operators is the case §5.6(b) supports.

### S0 — Establish the atom inventory (the prerequisite)

Nothing else should start before this exists, because every later stage is
defined against it.

The inventory is **discoverable, not inventable** — three sources already
constrain it and should be reconciled into one list:

1. **The Comprehensive Rules.** RULE 701's keyword actions are a closed,
   enumerated set, and RULE 700-701 plus the zone/counter/damage rules fix the
   ordinary operations. This is the authority.
2. **`game/effects/core.py`'s 457 registered types** — a *de facto* inventory,
   but polluted: a large share are one-card **verb-pair fusions** created
   precisely because the IR could not say "do A, then do B to what A produced"
   (`LivingWeaponEffect`'s docstring says so outright, §6). Separating true
   atoms from fusions is a deliverable of this stage, and the fusion list is
   the direct backlog for what composition must replace.
3. **The corpus**, as a frequency check and completeness test — §5.6(b)'s 130
   observed operations, ranked, so the inventory is ordered by real yield and
   any operation the rules imply but the corpus never uses is visible as such.

Each atom needs an explicit **argument frame** — the roles it takes (agent,
object, source zone, destination zone, amount, duration) — since it is the
frames, not the verbs, that composition operators plug together. §5.6(b)'s
"verb + argument frame" cut (11,532 distinct) shows frames are *not* yet
canonical; canonicalizing them is the substance of this stage.

**Exit criterion:** every one of the top-50 operations has a named atom with a
declared frame, and each of the 457 registered effect types is classified as
atom, fusion, or alias.

### S1/S2 — Composition over the inventory

Only once S0 exists do these have a well-defined target:

- **S1 — structured conditions.** Replace the 43 flat `_ALLOWED_CONDITION_KEYS`
  with subject-qualified predicates modelled on `static_conditions.py`'s
  `{kind, of, …}` plus its `"all"` combinator, reusing `condition_holds` (the
  precedent `effect_binder.py` already set for replacements).
- **S2 — composite IR nodes.** `seq`, `if/else`, `optional`, `for_each`, `bind`
  on `EffectSpec`, with `validate()` recursing. Bind onto the nested-spec
  machinery the engine already has (§6), so this needs little new engine code.
  It also closes a real hole: nested `params["effects"]` currently bypass
  `_clamp_params`, leaving `MAX_EFFECT_MAGNITUDE` unenforced below depth 0.

`bind` is what the devotion cluster in §3.4 works around; `if/else` is what the
kicked-override family works around. Each composition operator should be
justified by naming the fusion effects from S0(2) that it retires.

### S3 — Connective grammar

Rewrite `parse_effect_body` as recursive descent over the connectives in §5.2,
replacing the all-or-nothing `fullmatch` with a **residue** mechanism so a
partially-claimed clause hands its remainder on. Fix the two standing positional
gaps here: mid-body `you may`, and `UP_TO_ONE`'s hardcoded N=1.

This remains the highest-risk stage — every currently-MODELED card is re-derived
through it — and it is the one that must not be attempted before S0/S2, since
without an atom layer to hand residue *to*, recursive descent has nothing to
descend into. Mitigation is the existing suite plus a full-cache before/after
coverage diff.

### S4 — Slot grammars, re-scoped

`81c3320` showed the damage/destroy/exile rows are driven by genuine semantic
and parse-context variety; do not re-run that experiment. What it did not
examine is *cross-module* reuse — `static_handlers.py` imports five names from
`subgrammars` and not `TARGET`, `replacements.py` imports none, the same colour
dict is declared three times. Scope S4 there.

**First, regardless: merge or cherry-pick `81c3320`'s `09_` conclusion section
and `SELF_SUBJECT_PREFIX`** onto the working branch (§4.1).

### Gating

Each stage ships only if it (a) does not regress Commander-legal coverage and
(b) does not grow the enumerated row count — 394 `HANDLERS` rows plus 949
hand-authored catalogue entries. Note that S0 and S1 may legitimately move
coverage by zero: they are the substrate. The row count is the honest progress
metric for them, and §5.1's templates-per-card ratio (1.12 today) is the
headline to drive down.


## 8. Non-goals

This review does **not** propose relaxing any of the following, and no stage
above requires it:

- **The fail-closed coverage gate.** A card gets parsed effects only when every
  clause is claimed. A residue mechanism (S3) changes *which* unit fails, never
  *whether* a half-understood card can contribute effects.
- **The `type`-whitelist security boundary.** Nothing derived from card text
  becomes code. Composite nodes are structural; leaves stay whitelisted types,
  and every nesting depth continues to go through `build_effects`. S2 tightens
  this by extending clamping and condition validation to nested specs.
- **`PARSER_VERSION` discipline** and the ledger-backed coverage measurement.
- **`NEVER_SUPPORTED`** classification (Stickers &c.) stays a distinct verdict,
  out of the denominator.

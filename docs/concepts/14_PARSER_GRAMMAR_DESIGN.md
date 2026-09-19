# 14 — The atom/composition design: oracle text as a program

**Status:** design, 2026-09-08. **S0, S1 and S2 are implemented** (ENG-34,
ENG-35, ENG-36, all closed) and **S3 is closed** (ENG-37 — composition nodes
and fusion retirement):
`game/isa.py`, `scripts/isa_report.py`, `game/targeting.py`'s
`TARGET_FRAMES`, `game/continuations.py`, `game/effect_conditions.py`,
`game/effects/composition.py`, `game/effect_amounts.py`. S4–S5 are still
proposal. **S0b's cheap-exit checkpoint
(§8) passed** — all 50 top corpus operations resolve to one instruction with
a canonical frame — so the programme continues rather than being abandoned
here. See `Done_Backend.md` "Instruction-Set Architecture (ISA) &
Composition" for what landed and what the classification found.
**Follows:** [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](13_ORACLE_PARSER_GRAMMAR_REVIEW.md)
(the evidence) and [09_ORACLE_EFFECT_PARSER.md](09_ORACLE_EFFECT_PARSER.md)
(the current design).

`13_` established *what* is wrong: the parser enumerates whole-clause shapes over
an IR with no composition node, while the operation vocabulary underneath is
closed and small — **130 distinct operations, top 50 covering 94.9%**, against
21,194 whole-clause skeletons that are 93.1% singletons. This document is the
design that follows from that: **find the atoms, then compose them.**

> **Measurement caveat.** The structural counts here were read from source on
> 2026-09-08 while a large `models/`/`game/` package split was landing
> uncommitted (675 files in flight). They were read statically, not by importing
> a running engine. Re-derive before relying on any exact figure.
>
> **Partly discharged.** ENG-34 re-derived these against a live import and
> they hold: **254** public `RulesEngine` methods, **97** of them
> `request_*`/`resolve_*_choice` (27 + 68 + 2 strays), **457** registered
> effect types, **43** `_ALLOWED_CONDITION_KEYS`, **59** explicit
> `TargetSpec.kind` strings plus the 36-kind composed graveyard family (95
> total). `scripts/isa_report.py` re-derives the first three on demand.

---

## 1. The machine model

The organising idea: **a card's oracle text is a program registered onto a
machine.** It is not a script the engine reads top to bottom — it is a set of
declarations, each with its own linkage, that attach to a running system.

| machine concept | the rules | this codebase |
| --- | --- | --- |
| compilation unit | card oracle text | `normalize` → `segment_line` |
| declaration linkage | ability kind | `AbilitySpec.ability_kind` (7 kinds) |
| interrupt vector + handler | triggered ability (RULE 603) | `EventType` + `TriggeredAbility` |
| exported function + calling convention | activated ability (RULE 602) | `ActivatedAbility` + `ActivationCost` |
| `main()`, runs once | spell effect (RULE 608) | `spell_effect` |
| event middleware / rewriter | replacement effect (RULE 614) | `ReplacementEffect` |
| constraint graph, continuously re-derived | static ability (RULE 613) | `continuous.recompute` |
| LIFO job queue, re-entrant | the stack (RULE 405) | `GameState.stack` |
| cooperative scheduler | priority (RULE 117) | `pass_priority` |
| invariant sweep | state-based actions (RULE 704) | `check_state_based_actions` |
| **instruction set** | **RULE 701 keyword actions + zone / damage / counter / life ops** | **`RulesEngine` primitives** |
| blocking I/O | a player choice | `request_*` / `resolve_*_choice` |

The seven linkage kinds are already named in `spec.ALLOWED_ABILITY_KINDS`:
`spell_effect`, `triggered`, `activated`, `static`, `replacement`,
`enter_replacement`, `keyword`.

### 1.1 Two places the analogy must be corrected

These are not pedantry — getting them wrong would put ~4,000 lines of grammar in
the wrong layer.

**Static abilities are not instructions.** They never enter the instruction
stream at all. RULE 613 is a continuously re-derived constraint system: every
layer pass re-derives each permanent's characteristics from scratch
(`continuous.recompute`). The right analogy is an attribute grammar or a
spreadsheet's formula graph, not code. This is why `static_handlers.py` is a
separate 3,943-line grammar, and why a static's "condition" vocabulary
(`static_conditions.py`, 48 kinds with a real `"all"` combinator and an `of`
subject) is better-designed than the effect-side one — it was built as a
*predicate language*, because that is what statics need.

**Replacement effects are not interrupts.** RULE 614 rewrites an event *before*
it happens; a trigger fires *because* one happened. Middleware, not a handler.
Different registration, different composition rules — a replacement can consume
or transform its event, a trigger cannot.

Everything else — spell bodies, trigger bodies, activated-ability bodies — is
genuine instruction stream, and that is the part the atom/composition work
targets.

---

## 2. What an atom is

**An atom is one instruction: an operation plus its argument frame.** Not a
verb, and not an `EffectSpec` type.

Today four independent axes are flattened into one enumerated list. The 457
registered effect types and the 254 public `RulesEngine` methods are a
partially-filled **cross-product**:

| axis | what varies | where it lives today |
| --- | --- | --- |
| **1. operation** | `deal_damage`, `draw`, `exile`, `create_token`, … | `RulesEngine` methods |
| **2. operands** | agent, patient, source zone, destination zone, amount, duration | `TargetSpec`, `count_selector`, duration params |
| **3. composition** | seq, branch, bind, iterate, optional | **nothing — this is the gap** |
| **4. linkage** | which of the 7 ability kinds; how it registers | `AbilitySpec.ability_kind` |

Read the handler table through those axes and the duplication resolves:

- `damage_kicked_override` = operation × **composition** (a branch)
- `gain_life_and_draw_devotion` = operation × operation × **composition** (a shared binding)
- `damage_equal_to_power_previous` = operation × **operand** (a referent)
- the eight `*_two_color` rows = operation × **operand** (a filter)

Each axis is individually small. Their cross-product is not, and the cross-
product is what is currently being written out by hand.

**Classification is therefore not cataloguing — it is factoring.** For each of
the 457 effect types and 254 engine methods, decide: is this an *instruction*,
a *continuation pair*, a *fusion* (two instructions welded because the IR
couldn't sequence them), an *alias*, or a *one-card special*? The fusion list
is not a by-product — it is the direct backlog of what composition retires, and
it gives every proposed operator a concrete justification rather than a
speculative one.

The engine states the fusion problem itself, in `LivingWeaponEffect`:

> "there's no vocabulary for whatever the previous effect just made — an atomic
> effect class per verb pair was the only alternative."

---

## 3. The same disease exists one layer down

Reading the ISA statically produced the finding that most changes the plan.

**254 public `RulesEngine` methods — but 97 of them (38%) are `request_*` /
`resolve_*_choice` pairs** (27 `request_*`, 68 `resolve_*_choice`, plus
strays). Strip them and the instruction core is **≤157**, which still contains
one-card entries — against the **~130 operations the corpus actually uses**
(`13_` §5.6b). Those two numbers converging from opposite directions is the
strongest evidence that the ISA is real and bounded.

The 97 exist because **the engine has no general continuation primitive.** Every
"ask the player, then resume" is hand-written as its own syscall pair:
`resolve_slithermuse_opponent_choice`, `resolve_tainted_pact_choice`,
`resolve_scroll_rack_choice`, `request_word_of_command`. In machine terms:
no `await`, so every blocking call became a bespoke syscall.

**This is the parser's disease one layer down.** The parser enumerates clause
combinations because it cannot compose; the engine enumerates choice
interactions because it cannot suspend.

### 3.1 This is a hard prerequisite, not a cleanup

A general mechanism *does* exist: `_apply_effects_partitioned` parks the
remainder of a resolution on `GameState.deferred_effects` and
`RulesEngine.resume_deferred_effects` picks it back up. But it parks **the tail
of a flat list, by position**. It cannot resume into a nested structure.

Therefore: **`optional` and `for_each` are unimplementable until the
continuation mechanism is structure-aware**, because both must be able to
suspend inside a body and resume at the right point in a tree. Any plan that
schedules composite IR nodes before this will stall on it.

It is also the one piece of work here that is independently valuable and
independently testable, with **no parser changes at all**: collapse 97 methods
into one primitive plus a choice descriptor, keep the suite green.

---

## 4. Target architecture

```
oracle text
  │
  ▼  normalize                     (unchanged)
  │
  ▼  segmenter → linkage           axis 4: which ability kind, what registers
  │                                statics/replacements branch off here
  ▼  clause grammar                axis 3: seq / branch / bind / iterate /
  │   (recursive descent,                   optional, WITH RESIDUE
  │    hands residue on)
  ▼  atom grammar                  axis 1+2: operation + role frame
  │
  ▼  AbilitySpec (composite IR)    a tree, not a flat list
  │
  ▼  binder → engine               instructions + continuations
```

Two properties the current pipeline lacks, both load-bearing:

- **Residue.** A clause-level rule may claim part of a clause and hand the rest
  on. Today `EffectHandler.match` is `fullmatch` — all or nothing — so an
  unmodelable fragment discards the parse of every sibling that worked.
- **A shared role vocabulary.** Axis 2 must be one vocabulary used by both the
  parser and the engine. Today `TargetSpec.kind` is **59 explicit opaque
  strings** (plus a programmatically-composed graveyard family) dispatched by
  **58 hand-written `kind == …` branches** in `legal_targets`. Union types are
  spelled out as single strings — `artifact_creature_planeswalker_or_opponent`
  — rather than composed. The graveyard family, built as scope × type-filter by
  comprehension, is the one place the codebase already demonstrates the
  alternative.

The security boundary is unchanged and must stay so: composition nodes are
*structural*, leaves remain whitelisted `type` strings, and every nesting depth
continues to go through `build_effects`. Adding nesting to the schema also
closes a current hole — nested `params["effects"]` today bypass `_clamp_params`,
leaving `MAX_EFFECT_MAGNITUDE` unenforced below depth 0.

---

## 5. Staged plan

Dependencies are real; the order is not a preference.

### S0 — Establish the atom inventory *(no behaviour change)*

- **S0a — the ISA.** Derive the operation list from the Comprehensive Rules
  (RULE 701 keyword actions plus the zone-change / damage / counter / life
  operations). Classify all 254 `RulesEngine` methods and 457 effect types
  against it: *instruction* / *continuation pair* / *fusion* / *alias* /
  *one-card special*.
  **Exit:** every top-50 corpus operation has a named instruction; every
  registered type carries a classification.
- **S0b — the role frames.** One operand vocabulary shared by parser and
  engine, replacing `TargetSpec`'s opaque `kind` strings with structured
  filters (type, controller-scope, colour, qualifier). This is where `13_`
  §5.6b's 11,532 observed frames collapse.
  **Exit:** the top-50 instructions have declared frames; `legal_targets`
  dispatches on structure, not on 58 name branches.
- **S0c — the operators.** Name each composition operator *by the S0a fusions
  it retires*. An operator with no fusions behind it is not yet justified.
- **S0d — the linkage boundary.** Confirm statics and replacements stay outside
  the instruction stream (§1.1), and that `enter_replacement` is genuinely
  distinct from `replacement`.

### S1 — Continuations *(engine only, no parser change)*

Collapse the 97 `request_*`/`resolve_*_choice` methods into one continuation
primitive plus a choice descriptor, and make `deferred_effects` **structure-
aware** rather than list-position-based. **Blocks S3.**
**Exit:** suite green, method count down, no coverage movement expected.

**Do not invent a mechanism — generalize the one that already works.** MEC-69
(closed) built exactly this for one family, and the pattern it landed on is the
right one: `RulesEngine.enqueue_reflexive_trigger` (`game/rules/misc_mixin.py`,
already extracted with two callers) builds a fresh `TriggeredAbility` from
serialized payoff specs and appends it to `pending_triggers`, so the ordinary
resolve loop puts it on the stack and gathers its RULE 115 targets through the
normal interactive path. **A trigger on the stack is a resumable continuation
with correct target selection** — which is why that approach fixed the bug where
`pay_cost_then` ran its payoff off-stack and could never choose a target.

It also already carries a *mode* choice (`then_trigger_modes`), i.e. a branch
resumed after a suspension — the shape `optional`/`for_each` need.

S1 is therefore: promote `enqueue_reflexive_trigger` from a two-caller helper
into the general continuation path, and retire the bespoke pairs onto it.
Per this repo's own rule, that is citing an existing primitive rather than
proposing a new one.

> **Shipped (ENG-35), with one correction to the analysis above.** The
> resumption mechanisms were indeed not the problem and were left untouched:
> `enqueue_reflexive_trigger` still runs any payoff needing RULE 115 targets,
> and `deferred_effects` still suspends a resolution. What was actually
> written out 68 times was the *dispatch* — an identical guard/clear preamble
> per resolver, plus each kind's answer coercion split between the cascade
> and the resolver. `game/continuations.py` is that: a handler registry,
> `open_choice` / `resolve_choice`. 254 → 162 public methods, 367 → 23 lines
> of dispatch.
>
> **§3.1's claim that `deferred_effects` "cannot resume into a nested
> structure" is half wrong, and the wrong half is the expensive one.** It is
> already a LIFO stack and nesting through it already worked — an inner pause
> parks before the outer one and pops first. The missing piece was never the
> stack, only a loop counter: no frame could say "resume this body for item
> k, *then* continue at k+1". `DEFERRED_ITERATION` adds exactly that, which
> is the whole of what S3 blocked on. Anyone reading §3.1 as a mandate to
> rewrite the parking mechanism would have rewritten something that works.

### S2 — Structured conditions — **shipped** (ENG-36)

Replace the 43 flat `_ALLOWED_CONDITION_KEYS` with subject-qualified predicates
modelled on `static_conditions.py`'s `{kind, of, …}` + `"all"` combinator,
reusing `condition_holds` — the refactor `effect_binder.py` already performed
once for replacements. Removes the peeler cascade in `parse_effect_body` and
the four-edits-per-predicate tax.

Shipped as `game/effect_conditions.py`: `ConditionalEffect._condition_holds`
554 → 16 lines, the peeler cascade → one rule. Three corrections this section
earned, recorded so the next stage doesn't inherit them:

- **The cascade was 15 blocks, not 26.** 26 counts the distinct condition
  *outcomes* those 15 regexes produce. The same over-count risk applies to
  S3's "84 fusions" and S5's row counts — `isa.py` measures those, so they
  are safe, but this one was written from a reading rather than a query.
- **"Reusing `condition_holds`" turned out to mean something stronger than
  intended.** The plan reads as "model the effect vocabulary on the static
  one". What actually works is *delegating to it*: `static_conditions.py`
  already was the shared state-predicate vocabulary (statics, trigger
  intervening-ifs, and `binding/core.py`'s replacement gate all read it), so
  the effect layer resolves its extra referents and hands that evaluator a
  condition already pointed at the object. 15 of the 44 keys' predicates moved
  *into* the state vocabulary; only five genuinely need a `GameContext`. The
  side effect is the real win: all 65 state predicates are now reachable as
  effect gates, which is capability the plan never asked for.
- **The vocabulary needed `not`, and needed to be three-valued.** Roughly half
  the flat keys were booleans whose `False` spelling meant "the same question,
  negated" — a combinator, not a predicate. But negation is only correct once
  the evaluator can say "the referent doesn't exist" separately from "the
  answer is no", or "otherwise, …" fires when no clash happened. `all` alone
  (what this section proposed) is not a sufficient combinator basis for this
  vocabulary.

### S3 — Composite IR nodes — **closed** (ENG-37)

`seq` / `if-else` / `optional` / `for_each` / `bind` on `EffectSpec`, with
`validate()` recursing. Binds onto the nested-spec machinery the engine already
has (`pay_cost_then`, `repeat_process`, `create_delayed_trigger`), so little new
engine code — **provided S1 has landed.**

The "little new engine code" held: `game/effects/composition.py` is thin, and
the nodes reuse S1's iteration frame and S2's conditions as predicted. Three
things this section did not anticipate, recorded so S4 doesn't inherit them:

- **The nodes do not retire the fusions on their own.** 80 of the 84 have every
  part registered as a standalone instruction already, so the blocker was never
  the operation vocabulary *or* the composition axis. It is **axis 4,
  linkage**: a fusion exists because its second part must name what the first
  produced, and an effect's *operands* cannot name a referent.
  `exile_gain_life_equal_power`'s own docstring states it — "composing two
  effects here couldn't pass the power along". S2 built half of what is needed
  (a body can *ask* about `previous_target`/`entering`/`chosen`, and
  `effect_amounts` can measure one); the operand side has since been built as
  `game/effect_operands.py`, and three fusions retired onto it (84 → 81) —
  but **axis 4 is still not staged anywhere in this document**, which is the
  gap worth fixing here: S3 assumed composition alone would retire the fused
  types, and it does not.
- **`all` is not a sufficient combinator basis, and neither is a two-valued
  gate.** `if_else` needs "the referent doesn't exist" to be distinct from
  "the answer is no", or RULE 701.30d's "otherwise" fires whenever no clash
  happened and `else` becomes the catch-all for every unmodelled condition —
  fail-*open*. S2 shipped that three-valued evaluator for this reason; the two
  stages only fit together that way.
- **RULE 601.2c constrains which nodes may announce targets.** Only `seq` can:
  it runs every part. `if_else` doesn't know which branch will run and
  `for_each` doesn't know how many times, so neither may claim a requirement
  when the ability goes on the stack. Any S4 rule that puts a targeting clause
  inside a branch has to route the target through a sibling.

A **pre-existing RULE 608.2 ordering bug** had to be fixed before the nodes
could be trusted: `_apply_effects_partitioned` appended an enclosing list's
remainder *after* frames the paused effect had parked itself, and the deferred
stack pops from the top — so "each player sacrifices a creature, you gain 5
life" gained the life before the second player had sacrificed.

### S4 — Clause grammar with residue

Rewrite `parse_effect_body` as recursive descent over the connectives measured
in `13_` §5.2, replacing all-or-nothing `fullmatch` with residue. Fix the two
standing positional gaps here: mid-body `you may`, and `UP_TO_ONE`'s hardcoded
N=1.

**Highest-risk stage** — every currently-MODELED card is re-derived through it.
Mitigation is the existing suite plus a full-cache before/after coverage diff.
It must not precede S0/S3: without an atom layer to hand residue *to*, recursive
descent has nothing to descend into.

### S5 — Slot grammars, re-scoped *(closed: PAR-63 / PAR-116)*

`81c3320` already showed the damage/destroy/exile rows are driven by genuine
semantic and parse-context variety, not redundant surface grammar — **do not
re-run that experiment.** What it did not examine is cross-module reuse:
`static_handlers.py` imports five names from `subgrammars` and not `TARGET`;
`replacements.py` imports none; the same colour dict is declared three times.

**Exit, 2026-09-19.** PAR-63 removed the concrete duplication: all consumers
now share `COLOR_LETTERS`, `replacements.py` imports it, and the meaningful
printed-card-type alternation is `CARD_TYPE_WORD_ALT`. PAR-116 re-audited the
remaining premise live: `TARGET` maps RULE 115 target-selection language to
an engine target kind, whereas statics test criteria against an already-chosen
target and take no targets themselves. Sharing it would be a category error,
not grammar reuse. No row-count or coverage change was appropriate.

---

## 6. How progress is measured

Coverage is the wrong metric for the early stages and will mislead if used
there. S0 and S1 should move it by **zero** — they are substrate.

| stage | primary metric |
| --- | --- |
| S0 | every top-50 operation classified + framed; fusion backlog enumerated |
| S1 | `RulesEngine` method count (254 → target ≤170); suite green |
| S2 | condition-key count (44 flat → 5 context predicates over 65 shared state ones); peeler cascade removed (15 → 1); `_condition_holds` 554 → 16 lines ✓ |
| S3 | the five nodes exist and are used ✓; fusion effect types retired ✓ |
| S4 | Commander-legal coverage; templates-per-blocked-card (**1.12 today**) |
| S5 | enumerated row count (394 `HANDLERS` + 949 catalogue entries) |

The standing gate from `13_` still applies to every stage: **do not grow the
enumerated row count.** Coverage bought by adding one-card rows makes the
underlying ratio worse, not better.

---

## 7. What this produces as tickets

The stages themselves are **`ENG`**, not `MEC`. Continuations, structured
conditions, composite IR nodes, a clause grammar and slot grammars are engine
and parser *architecture*; none is "a named MTG mechanic with no engine
primitive yet". `BACKLOG.md`'s `ENG` section is currently empty — this work
repopulates it, paired with `PAR` tickets for the parser-side halves the same
way `PAR-56`/`PAR-58`/`PAR-59` already name their engine halves.

| stage | category |
| --- | --- |
| S0a/b/c/d — inventory, frames, operators, linkage | `ENG` (+ `PAR` for the frame vocabulary shared with the parser) |
| S1 — continuations | `ENG` |
| S2 — structured conditions | `ENG` + `PAR` |
| S3 — composite IR nodes | `ENG` + `PAR` |
| S4 — clause grammar with residue | `PAR` |
| S5 — slot grammars | `PAR` |

**`MEC` tickets do fall out — from S0a specifically, and by construction.**
Deriving the ISA from the Comprehensive Rules and diffing it against
`RulesEngine`'s actual primitives yields precisely "operations the rules require
that the engine cannot perform", which is the literal definition of the `MEC`
category. **That diff *is* a systematically-generated `MEC` backlog**, replacing
the current card-by-card discovery route (a card fails → a primitive turns out
to be missing → file a `MEC`).

Expect them to be *fewer and smaller* than the historical `MEC` stream, for a
structural reason: many past `MEC` tickets were really composition gaps wearing
a mechanic's name. MEC-69 ("Modal reflexive continuations") is the clearest
case — it is a continuation/branch problem, not a mechanic. S0a's atom / fusion
/ alias classification is what tells the two apart before a ticket is written.

**Reconcile with the existing feeder rather than duplicating it.**
`scripts/commander_tail_report.py`'s bucket D already routes ~132
Commander-legal cards to `MEC-*` via a signature table. Its labels used to cite
`(MEC-47)`, `(MEC-48)`, `(MEC-49)` and a `PAR-30:` prefix — all stale, since
MEC-47/49 and PAR-30 are closed and MEC-48 is parked in `DEFERRED.md`. **That
has been corrected**: the labels now name the *missing primitive* rather than a
ticket id, and `BACKLOG.md`'s `MEC` section carries a `(none open.)` marker
explaining the routing. S0a still owns the substantive half — deriving the
CR-versus-engine diff and filing it as fresh `MEC-*` tickets — because that is
the same ground truth it has to read anyway.

---

## 8. Risks and open questions

- **The prior negative result.** `81c3320` prototyped a clause-tier aimed at
  cutting handler count by absorbing surface phrasing, and rejected it. This
  design is a *different* claim — composition over a bounded ISA, measured by
  coverage — but its instruction stands and applies here: measure a family's
  genuinely-duplicated vs genuinely-distinct rows before touching it. **That
  commit is not on `Commander-Legal-Trail`; merge or cherry-pick its `09_`
  conclusion section and `SELF_SUBJECT_PREFIX` first**, or it will keep being
  rediscovered.
- **S4 is a rewrite of the highest-traffic code path.** There is no partial
  rollout: either `parse_effect_body` is recursive descent or it is not. The
  only real mitigation is the coverage diff.
- **Unvalidated assumption.** That a canonical role frame (S0b) exists for most
  instructions is asserted from the 130/11,532 gap, not demonstrated. **S0b is
  the checkpoint at which this design can still be abandoned cheaply** — if
  frames do not canonicalize, S3/S4 lose their footing.
- **Open:** whether `keyword` linkage stays a separate ability kind or becomes
  a macro expanding to instructions + statics. RULE 702 keywords are defined
  as shorthand, which argues for expansion, but the catalogue's ~195 rows are
  recognition-only today and expanding them is its own project.
- **Open:** whether replacement effects get their own composition operators
  (`instead`, `rather than`) or reuse the branch node. They rewrite events
  rather than sequencing instructions, so probably the former.

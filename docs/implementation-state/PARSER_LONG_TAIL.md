# Oracle parser: the long tail — strategy & worked examples

The **examples** document of the three-way split (see
[BACKLOG.md](BACKLOG.md) for open tickets, `Done_*.md` for worklogs). Nothing
here is a ticket to close; it is the standing method for the indefinite part
of parser coverage, plus enumerated samples that calibrate how that tail
actually behaves.

Tracked in the backlog as a single standing entry, `PAR-12`.

**What does not belong here.** This file used to carry a per-`PARSER_VERSION`
changelog — ~1,500 lines of "v*N* shipped *X*, +*M* cards". That is a worklog,
and it lived here in duplicate: of the 426 distinct code identifiers it named,
399 were already documented in `Done_Backend.md`, usually in more depth and
filed under the subsystem the primitive belongs to. It was removed on
2026-09-09; **git history has it** if you need a specific version's wording.
The rules that replace it:

- **What shipped, and why it was built that way** → `Done_Backend.md`, under
  the subsystem heading for the primitive (extend the existing entry, don't
  append a new one).
- **What is still open** → `BACKLOG.md` if it is schedulable, or the
  *Known-open clusters* section below if it is long-tail residue.
- **Method, recurring lessons, worked samples** → here.

## Where coverage stands

**55.3% covered — 19,406 / 35,095 — as of 2026-10-01, PARSER_VERSION 567** (PAR-139 closed + PAR-109 batch, +131 over v566, 0 regressed — group qualifier tail ("creatures you control with `<qualifier>`"), plural-subtype group pump, counter replacements "plus 1 of each kind", untap-during-each-untap-step, activate-as-though-haste, X-colour lock on activated abilities, granted land mana abilities with spend restrictions, prevention riders. Earlier: PAR-136/137/138/139 batch, +99 over v565, 0 regressed — flicker with a delayed return, impulse-draw variants, the "counters are put on" trigger head, entry counters for the others, prevented-amount riders, plus three general parser fixes (sentence windows, mid-body "where x is", list commas in a trigger condition). Earlier: PAR-144 dig family, +115, 0 regressed — one grammar over count / kind / destination / rest (`catalogue/dig.py`); the card pool also grew since v564, so the denominator moved. Earlier: PAR-135 + PAR-121: +82, 0 regressed — the named-counter kind became an open axis, plus action limits, power-only doubling, additive colours, Equipment targets; 4 wrong-but-MODELED families corrected on the way. PAR-134 + PAR-129, two wrong-but-MODELED fixes: +2 covered, −24 honestly UNMODELED — a count that fell because it got more honest. MEC-105 adds temporary layer-6 keyword loss and its gain/loss, P/T/loss, group-subject, previous-subject, and attached-static parser forms: +32 since v553, 0 regressed. MEC-106/MEC-107 at v553 added Gift/Expend and related residue: +23 since v552. PAR-123 at v552 generalized a group trigger's firing-object referent: +154 since v551, 0 regressed.)
Commander-legal slice (the one the product actually plays): **58.1% —
18,655 / 32,116** (measure with `--commander-legal-only`).

### PAR-124 closes completely: player-events, X-tokens, a targeted delayed trigger, a hand-zone duplicate, an optional-attach composition — and the controller-binding bug the targeted variant first exposed (PARSER_VERSION 463)

- **What:** the last seven cards of PAR-124's own scope, each its own small distinct primitive —
  see `Done_Backend.md`'s full write-up. +40, 0 regressed.
- **Lesson — a "no residue" instruction is itself useful triage pressure.** Several of these
  (Bubbling Muck/High Tide's `TAPPED_FOR_MANA` recipient, False Cure's `event_player` selector,
  Spellchain Scatter's hand-zone copy) turned out to need *no new primitive at all* once actually
  investigated — only a missing parser recognizer over an already-shipped engine mechanism. The
  ticket's own prior write-up had guessed several of these needed real new engine work; checking
  each one directly (rather than trusting the earlier guess) found four of six were pure
  recognition gaps. Re-verify a "needs a new primitive" claim before believing it, every time —
  this project's own recurring lesson, applied once more.
- **Lesson — a targeted variant of a group-subject mechanism needs its own referent design, not a
  copy-paste of the group one.** `CreateTurnTriggerEffect.target_kind`'s first cut rebuilt the
  ability with the *chosen target* as its whole `source`, reasoning that "self"-referential effect
  bodies would then naturally resolve against it — true for Graceful Reprieve's own "return that
  card," which is precisely why it shipped looking correct. But an ability's `source` is silently
  overloaded in this codebase to mean two different things whenever they happen to coincide: "the
  object RULE 603.1's condition is about" and "whose controller 'you' means." For every ability
  before this one they're the same object (a permanent's own ability). The instant a *target*
  becomes the condition's subject while the ability's controller stays the caster, the two split —
  and nothing catches this at the parse level, since both readings produce a perfectly well-formed
  spec. It only ever surfaces at runtime, and only for a body that reads an untargeted "you" while
  under a targeted condition — exactly the reason this project's own testing discipline insists on
  a real `GameEngine` run over an *adversarial* board (here: target an opponent's own creature)
  before trusting a parse verdict, not just the card the ticket happened to be written against.
- **Lesson — `OptionalEffect.target_specs`'s own docstring already answered the "can an optional
  wrapper have a target" question before Magitek Scythe asked it.** `_may_effect_then`'s
  target-rejecting design (built for a genuinely different shape — a mid-resolution "you may" with
  no RULE 115 target at all) reads, at a skim, like "an optional composition can't have a target."
  It was never a general rule; it was that *specific* composition's own scope. The actual answer
  — `seq`/`optional`/`bind` can all announce targets, `if_else`/`for_each` can't, because RULE
  601.2c only needs to know the body runs at all, not which branch or how many times — was already
  written down. Reading the primitive's own docstring before concluding a shape is unsupported
  would have skipped a chunk of this investigation.

### PAR-124 residue, second batch: "must be blocked this turn if able", animate-land/flash/tap-selector, a group-subject copy (PARSER_VERSION 462)

- **What:** five shapes all reuse the identical `"must_be_blocked"` flag-keyword grant (a bare
  clause, a pump-clause "and must be blocked…" tail, a `previous_subject` pronoun tail, and a
  group-subject pronoun tail) — no new engine code, only the missing parser rows; the animate-land
  family gained a `you control`/`creature_or_land` target-kind axis plus a missing "dinosaur"
  qualifier word; `GrantFlashUntilEndOfTurnEffect` gained a `card_types` filter for "cast `<type>`
  spells this turn as though they had flash"; `continuous.group_selector_objects` gained a
  colour-scoped `creatures_you_control_of_color_<letter>` branch for "untap all white creatures you
  control"; and `CopyPermanentEffect.referent="trigger_event"` (already built for Ashling, the
  Limitless) just needed a group-subject-gated parser row for "create a token that's a copy of
  **that creature**." +23, 0 regressed.
- **Lesson — a diagnosed-composed-head guard can reject a correct answer, not just a wrong one.**
  `segmenter._group_it_would_hit_source` exists to catch a group-subject body whose effect has
  `target_kind: None` and would therefore silently act on the ability's own *source* instead of the
  trigger subject. It has no way to tell that apart from an effect that has *already* been
  correctly retargeted through a different mechanism (`referent="trigger_event"` rather than
  `target_kind`) — so widening `copy_permanent`'s own group-subject reach tripped the very guard
  meant to prevent this class of bug, on a case where the bug didn't exist. Fixed with a narrow,
  named exemption rather than loosening the guard's general shape. Any future group-subject
  widening on an effect that resolves its referent through something *other* than `target_kind`
  should check this guard first, the same way this one should have been checked before, not after,
  writing the new row.
- **Lesson — "it's still a `<land>`" reminder sentences aren't a small detail, they're a trap for
  the generic connector-split.** The generic `previous_subject` pipeline (split on ".", parse each
  part, thread the pronoun forward) can't claim a pure-reminder sentence on its own — nothing
  builds an `EffectSpec` for "it's still a land" alone — so a three-sentence body (animate clause,
  reminder, tail) fails the *whole* thing closed the moment the reminder sits between the clause
  that creates the referent and the clause that needs it. Every animate-land row that might have a
  reminder sentence in the middle has to fold a trailing pronoun tail into its *own* regex instead
  of trusting the generic split — the same reasoning the already-shipped `_ANIMATE_SELF_LEADING_
  EOT_RE` had already worked out for its self-form sibling, just not yet generalized to the target
  form until this batch needed it.

### PAR-124 residue: "copy that spell X times", and a delayed trigger's own group pronoun (PARSER_VERSION 461)

- **What:** "copy that spell X times"/"an additional time" (Storm King's Thunder, Howl of the
  Horde's Raid-gated second ability) widens the existing `_COPY_THAT_SPELL_RE` count suffix; the
  "X" sentinel needed `_substitute_x` to reach one level deeper than before — into a
  `CreateTurnTriggerEffect`'s own `inner_specs` (raw `{"type","params"}` dicts, not yet built into
  real effects at the point this spell's own announced X is known). Separately, `create_delayed_
  trigger`'s `capture` never had a `trigger_subject` mode — every group-subject "it"/"that
  creature" `_stamp_group_pronoun` (PAR-123) already retargets for `tap`/`return_to_hand`/`exile`
  had a real hole for a *delayed* tail: "whenever a Minotaur attacks this turn, it gets +2/+0 …
  Destroy **that creature** at end of combat." (Consuming Rage) was silently destroying the
  ability's own source, since `previous_or_self`'s fallback chain has nothing upstream to fall
  back *to* under a group subject. +4 (Storm King's Thunder, Howl of the Horde, Consuming Rage,
  and — found executing Consuming Rage's fix — Rienne, Angel of Rebirth, whose own "…dies, return
  it to its owner's hand at the beginning of the next end step" hit the identical capture bug),
  0 regressed.
- **A second, real bug the fix surfaced, not just the parse gap:** `ReturnSpecificToHandEffect`
  (Ilharg/Zara/Alora's battlefield-loan bounce) was unconditionally battlefield-only — correct for
  *that* family (RULE 400.7: a permanent that left some other way before the delayed return fires
  is a new object, gone for good), but wrong for Rienne, where the delayed trigger's own firing
  event *is* the move to the graveyard, so "it" names the very card sitting there. A single shared
  zone-check would have gotten one of the two families wrong; `ReturnSpecificToHandEffect` gained
  an `allow_graveyard` flag `CreateDelayedTriggerEffect` sets only when the captured referent's
  origin was a `DIES` event — a capture-mode-scoped fix, not a blanket "return from anywhere"
  widening. Verified by execute test both ways: Ilharg-shaped tests (`test_par30_delayed_return_
  to_hand_tail.py`) untouched, Rienne pulls the destroyed creature out of the graveyard exactly at
  the next end step and not before (`test_par123_group_pronoun.py`).
- **Lesson:** a "such-and-such capture falls back to the source" gap, once found for one effect
  type, is worth checking against every *other* effect type the same pronoun-retargeting axis
  reaches — `create_delayed_trigger` had been sitting right next to the already-fixed `tap`/
  `return_to_hand`/`exile` trio (PAR-123) the whole time. Two long-standing pinned "fails closed"
  tests (`test_par119_object_trigger_head.py`) had to flip from asserting `modeled is False` to
  `True` once this landed — a reminder that a negative test pinning a *known* gap needs revisiting
  the moment the ticket that names it closes, not left to bit-rot as a stale regression guard.

### PAR-119 at v455–456: attack / block / player-event heads, and what executing them found

- **What:** attack batches over a new `ATTACKERS_DECLARED`, "isn't blocked", "attacks while
  `<state>`", the block relation over `related_ids`, player events as one actor × verb × tail
  grammar, "A or B" as two triggers, the group "it gets +N/+N" pump, the next-cast copy spells. +139 (16,896 → 17,035).
- **Lessons worth keeping:** (1) *the same words, two objects*: "it"/"that creature" under a
  group trigger, "that creature" under a block relation, and "~" all reach the binder as one
  untargeted spec that acts on the source — only the parser sees which was printed, so it must
  stamp the reading (`trigger_subject`, `trigger_related`) rather than let the binder guess.
  (2) *A shared word can be a shared connective, not a per-row one*: "Otherwise" was a row of the
  leading-gate table hard-wired to a clash — seven cards claimed it wrongly for months. When a
  word appears in a gate table, ask what every card using the word would need, not just the card
  that put it there. (3) *An "or" between two heads is only two triggers when nothing trails it*:
  "…or cast a spell from anywhere other than your hand" qualifies both verbs. (4) A shared event
  cannot answer a question that depends on one listener's own filter ("that many") — refuse the
  body. (5) A leading-if gate has to be decided once (`if_else`) when an earlier effect changes
  what it reads.

### PAR-119: composed object-event head (PARSER_VERSION 450)

- **What:** One noun-phrase grammar (`catalogue/characteristic_phrase.py`, subtypes
  from the generated `subtype_vocabulary.py`) × the verbs enters / dies / attacks /
  blocks / leaves, "deals [combat|noncombat] damage [to …]", "sacrifices / discards
  `<object>`" (`catalogue/object_trigger_head.py`), plus "X and whenever Y" split into
  two triggers. +146 cards (16,333 → 16,479), 0 regressed.
- **Lessons worth keeping:** a parse verdict is not proof — *executing* the newly claimed
  cards' bodies found four wrong-but-MODELED shapes (an event missing the `player_id` an
  `event_player` body reads, a bare "it" that acts on the source under a group subject, a
  `previous_target` referent used for "on it", a "for each" that dropped its printed
  multiplier). For any new head, list every (event, referent) pair the newly claimed bodies
  use and check that event's payload carries it. Heads that still need a new engine event
  (crank, exploit, saddle, expend, commit a crime, unlock a door) are not composition work.

### PAR-119 pilot: composed cast-trigger head (PARSER_VERSION 449)

- **What:** `parser_probe.py composition` showed 849 cards blocked *only* by
  their trigger head (the body parsed alone), 138 distinct cast heads among
  them. One composed row now builds a `SPELL_CAST` head from shared word tables
  instead of one regex + dispatch block per adjective combination; +86 cards
  (16,247 → 16,333), 0 regressed. Recorded gaps left on the axis (subtype words
  closed at v450 by the generated vocabulary): ordinals
  ("your first spell each turn"), "or copies" (no copy event).
- **Verification:** `tests/test_par119_cast_trigger_grammar.py` (grammar,
  fail-closed cases, real cards, and execute tests that fire real `SPELL_CAST`
  events); five stale "stays unclaimed" pins were updated to the new truth.

### PAR-98: Small verified residue batch #2 (PARSER_VERSION 448)

- **What:** The fourteen-shape residue batch closed: +63 cards over PAR-97
  (16,184 → 16,247), each shape with an execute-level test. The last pass
  added Meanders Guide's RULE 603.12 reflexive trigger, the "except by
  creatures with haste" family, "When you sacrifice a Clue", the suspend
  last-time-counter trigger and a noncreature-spell activation gate. Alora,
  Cheerful Scout/Thief (Alchemy `perpetually`, an engine non-goal) and four
  other single cards went to [singletons.md](singletons.md).
- **Verification:** `tests/test_par98_residue_batch.py`; full cache is
  16,247 / 34,811 (46.7%) and Commander-legal coverage is 15,609 / 31,830
  (49.0%).

### PAR-97: Mill graveyard-entry batches (PARSER_VERSION 447)

- **What:** `CARDS_MILLED` preserves the actual moved cards and their type
  information per milling instruction; `MILLED_CARD` covers the singular
  counterpart. Batch triggers therefore fire exactly once while singular
  card triggers still fire per card. Eight former SOLO cards are modeled.
- **Verification:** `tests/test_par97_mill_batch_triggers.py`; full cache is
  16,184 / 34,811 (46.5%) and Commander-legal coverage is 15,548 / 31,830
  (48.8%).

### PAR-96: Total-mana cast-trigger riders (PARSER_VERSION 446)

- **What:** Reusable cast-trigger decomposition now makes an additive rider
  an independently gated ability and makes an `instead` rider mutually
  exclusive with its low-mana branch. Tellah's two additive thresholds also
  retain its damage amount from the `SPELL_CAST` event. Ten former SOLO
  cards are modeled. Phoenix of Iteration remains deliberately unmodeled:
  its Alchemy `perpetually` modification is an engine non-goal, not a
  total-mana-rider gap.
- **Verification:** `tests/test_par96_mana_spent_riders.py`; full-cache
  coverage is 16,176 / 34,811 (46.5%) and Commander-legal coverage is
  15,540 / 31,830 (48.8%).

### PAR-95: Adamant per-mana-type riders (PARSER_VERSION 445)

- **What:** Cast payment now records exact WUBRG and colorless quantities.
  Closed Adamant parsing covers additive spell riders, entry counters,
  amount overrides, a preserved first target after a fight, and Sundering
  Stroke's divided-damage replacement.
- **Verification:** `tests/test_par95_adamant.py`; 14 former SOLO cards are
  modeled. The two remaining probe hits have independent unclaimed clauses.

### PAR-94: Specialize conditional discount — increment (PARSER_VERSION 444)

- **What:** A closed Specialize rider now preserves its conditional dynamic
  reduction in keyword data and the binder applies it to the generated
  Specialize activation.
- **Verification:** `tests/test_par94_activation_cost_reductions.py`; fresh
  full-cache `--no-db` measurement.

### PAR-94: Conditional cost gates — increment (PARSER_VERSION 443)

- **What:** Existing conditions now recognize legendary-creature control and
  instant/sorcery graveyard thresholds for activation-cost reductions.
- **Verification:** `tests/test_par94_activation_cost_reductions.py`.

### PAR-94: Conditional graveyard-mana-value discount — increment (PARSER_VERSION 442)

- **What:** A flat activation discount can now carry a live
  `active_if` threshold; Sewer Crocodile's five distinct mana values in the
  controller's graveyard are counted once per mana value.
- **Verification:** `tests/test_par94_activation_cost_reductions.py`.

### PAR-94: Per-unit activation-cost reductions — increment (PARSER_VERSION 441)

- **What:** Trailing "this ability costs {N} less to activate for each …"
  clauses now populate `ActivationCost.dynamic_reduction` through a closed,
  live-selector vocabulary, including counters, card zones, basic land types,
  subtypes, modified creatures, and power-qualified opposing creatures.
- **Verification:** `tests/test_par94_activation_cost_reductions.py`; the
  residual broad-probe hits are separate X, surcharge, conditional, or
  independently unmodeled effect-body shapes.

### PAR-92: Small verified residue batch (PARSER_VERSION 440)

- **What:** The five independently verified shapes are modeled: second-spell
  cast discounts, domain reductions for basic land types, self
  graveyard-to-library replacements, Triple Threat's commander-damage
  multiplier, and attack-triggered Meld.
- **Verification:** `tests/test_par92_cost_reductions.py` and
  `tests/test_par92_residue_batch.py`; all ticket clauses are claimed by the
  cache probe.

### PAR-91: Optional collect-evidence conditional riders (PARSER_VERSION 439)

- **What:** Optional collect-evidence cast costs now feed the existing
  cast-state condition into self cost reductions; Lamplight Phoenix's
  exile/evidence/reflexive tapped return resolves atomically.
- **Verification:** `tests/test_par91_collect_evidence_conditions.py`.

### PAR-90: Suspected-state resolve-time referents (PARSER_VERSION 438)

- **What:** Conditions now distinguish a source, attached Aura host, and
  activation-cost sacrifice's suspected flag. Frantic Scapegoat's optional
  non-target choice uses the general pending chooser, then clears its source
  only after a creature was chosen.
- **Verification:** `tests/test_par90_suspected_referents.py`; the suspected
  probe has no remaining SOLO blockers.

### PAR-89: Named-counter entry cycles (PARSER_VERSION 437)

- **What:** Tapped charge/depletion lands now receive their counters as well
  as entering tapped; hand-cast divinity-counter Myojin gates read cast zone.
- **Verification:** `tests/test_par89_entry_counter_cycles.py`; no ticket
  clause remains in the cache probe.

### PAR-88: Graveyard land-play permission (PARSER_VERSION 435)

- **What:** "You may play lands from your graveyard" binds a land-only
  `GraveyardCastPermissionEffect`, distinct from Muldrotha's per-type grant.
- **Verification:** `tests/test_par88_graveyard_land_permission.py` covers
  parser output and playing a graveyard land end to end; all five SOLO cards
  model.

### PAR-87: Sacrifice-or-mana additional cost (PARSER_VERSION 434)

- **What:** "Sacrifice a creature or pay {M}" represents both mandatory
  RULE 601.2b alternatives: the normal cast pays the fallback mana, while a
  second cast action pays by sacrificing a selected creature instead.
- **Verification:** `tests/test_par87_sacrifice_or_mana_cast_cost.py` covers
  the parser plus both payment branches; all five exact cache cards model.

### PAR-86: Targeted graveyard-card shuffle (PARSER_VERSION 433)

- **What:** The target-player wording for shuffling up to N targeted cards
  from that player's graveyard into their library now reaches the existing
  Quandrix Command shuffle primitive. The target determines the graveyard and
  library; resolution selects up to the stated number of cards.
- **Verification:** `tests/test_par86_target_graveyard_shuffle.py` covers the
  emitted spec, rejects the self-graveyard near miss, and parses Dwell on the
  Past. Five cards newly model; Witness the Future remains open only for its
  independent following library look-and-reorder clause.

Measure with `scripts/coverage_report.py` (ledger-backed via
`services/coverage_db.py`), against the full ~35k-card Oracle universe;
add `--commander-legal-only` for the Commander slice, which records its own
`<v>-commander` snapshot row. `scripts/commander_tail_report.py` (read-only)
then segments the still-UNMODELED Commander-legal cards by *cause* — wrapper
re-measure (A), recurring template → `PAR-*` (B), set-specific → `PAR-*` (C),
missing engine primitive → `MEC-*` (D), bespoke hand-authoring tail →
PAR-12 (E).

"Covered" = parser-`MODELED` **or** hand-`AUTHORED`. Re-run the report rather
than trusting a figure quoted here, in `CLAUDE.md`, or in the Engine-Status
tab; after any change here, sync all three.

Goal is literal 100% of the Commander-legal slice (minus the RULE 123 sticker
non-goal); expect bucket E to stay several thousand one-card entries after
every generalisable cluster is closed.

**Bump `PARSER_VERSION` (`parser/oracle/gate.py`) in the same session you add
a handler.** The ledger is keyed on content-hash **+ version**, so measuring
twice within one batch (bump, measure, add more handlers, measure again)
silently reuses the first run's rows. Either bump again or delete that
version's rows. Hand-authoring alone needs no bump — `content_hash` folds in
`card_registry.is_registered`.

## How the tail gets closed

The remaining ~25k templates are, by construction, not generic. This is an
*indefinite program*, not a finite batch list, and proceeds two ways:

1. **Narrow parser extensions** for singleton shapes that still generalize a
   little — a slightly different targeting scope, a compound filter.
   Preferred: each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/card_catalogue/`
   ([authoring guide](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
   only after confirming no near-miss handler would unlock a cluster.

Deterministic-first: classification, scaffolding and measurement are pure
code, no LLM. LLM/subagent effort (Sonnet/Haiku only, file-ownership waves)
goes only to finalizing a handler's regex/builder semantics and to
hand-authoring the tail.

A few items are deliberate non-goals — the legacy pre-2021 werewolf
template, silver-border/acorn/un-set cards — excluded from the denominator or
accepted as permanently unmodeled. Stickers and Attractions are project
non-goals tracked in [BACKLOG.md](BACKLOG.md) under MEC.

## The Commander-legal tail sweep (PAR-31…PAR-53)

The Commander-legal slice (`--commander-legal-only`) is the one the product
actually plays, so it gets its own dedicated sweep on top of the two tracks
below — not a third, separate program, just a different **starting point**
into the same indefinite tail: `scripts/commander_tail_report.py`
(read-only) segments every still-UNMODELED Commander-legal card by *cause*
into six buckets:

- **A** — block-wrapper / segmenter re-measure (no ticket; usually a red
  herring — see "A ranked template that is a block *wrapper*…" under
  *Lessons that keep recurring* below before trusting one)
- **B** — recurring template → the *basic mechanics* track below
- **C** — set-specific mechanic → the *set-specific mechanics* track below,
  worked deck-first
- **D** — missing engine primitive → its own real `MEC-*` ticket in
  [BACKLOG.md](BACKLOG.md) — a primitive is schedulable, closeable work
  with an end state, unlike the sweep itself, so it doesn't live here
- **E** — bespoke hand-authoring tail → this document's own indefinite
  program, same as every other singleton (PAR-12)
- **F** — never-supported, out of the denominator (Stickers)

**Discipline:** re-run the tool and `parser_probe.py blocked '<regex>'`
before starting a batch — any `#` count quoted below is stale the moment
it's read; the tool's own live output is the only trustworthy count. Finish
a batch end to end without leaving residue before starting the next one
(narrate in `Done_Backend.md`, bump `PARSER_VERSION`, sync the three
coverage figures — a batch that turns out fully hand-authored needs no
version bump). When a batch lands a genuinely new engine primitive, sweep
`BACKLOG.md` for any *other* ticket that primitive also closes or narrows —
a primitive landing is exactly the moment this project has historically
forgotten to look (`CLAUDE.md`'s own no-half-implementations rule).

**Ticket-id bookkeeping:** `PAR-31` through `PAR-53` were this cluster's own
reserved id block; every one of them that shipped is closed and narrated in
`Done_Backend.md`. Bucket C's own three-line placeholder ("file from the
next free id … when their batch comes up") was later resolved into real
tickets — `PAR-69` through `PAR-72`, filed and closed 2026-09-14 — rather
than reusing the `PAR-31…PAR-53` block itself. The first free parser
ticket id past this whole history is **`PAR-73`** (checked 2026-09-15).

**Status (2026-09-15):** PAR-67/PAR-68 (the last two dedicated Bucket-B
tickets before this pass) closed 2026-09-14. The same day, a fresh sweep
of `commander_tail_report.py`'s Bucket B/C/D histograms (`--min-cluster 5`)
traced and verified a further 19 PAR tickets (PAR-74…92) and 8 MEC tickets
(MEC-89…96) — filed in `BACKLOG.md`, not narrated here per this file's own
"what does not belong here" rule. Two of the report's own bucket-D labels
turned out stale on inspection (a dice subsystem and meld both already
existed; MEC-90/PAR-92 respectively) — another instance of the "needs a
new primitive" trap below. PAR-79 (the sweep's biggest single cluster, 105
SOLO) got its first increment the same day (v387, +24) — its own residual
~81 cards are, on inspection, several distinct smaller shapes rather than
one dominant remaining template, itself a small worked example of the
"ticket estimates are wrong in both directions" lesson below (the raw
regex-match count overstated how much *one* handler would close, but the
gap didn't vanish either — it fragmented). Bucket C (set-specific,
deck-first) was resolved into five tickets the same day, traced
card-by-card with `commander_tail_report.py` + `parser_probe.py
card`/`blocked` rather than taken at the report's own loose keyword-match
counts — two of its five raw clusters turned out to be residue from
*already-closed* tickets (Party, Ki-counter/Spirit-or-Arcane) whose real
remaining gap was a generic primitive, not the named set mechanic. PAR-69
through PAR-72 all closed 2026-09-14 (`Done_Backend.md`'s "Keyword
Catalogue" and "Oracle-Text Parser Front-End" entries); the other three —
`MEC-86` (Prepared), `MEC-87` (Horsemanship), `MEC-88` (Banding), each
needing a genuine new engine primitive before a parser handler could mean
anything — closed 2026-09-15 (`Done_Backend.md`'s "Prepared cards",
"Horsemanship" and "Banding" entries; also reflected in the Two Tracks
table below). Attractions (RULE 717) and Conspiracy draft-matters were the
two Bucket-C items resolved as permanent non-goals instead, moved to
[DEFERRED.md](DEFERRED.md)'s "Permanent non-goals" section 2026-09-14.

Residue traced and deliberately left [PAR-12] bespoke tail rather than
promoted to its own ticket: PAR-71's own "that spell's mana value" pairing
on `lose_life`/`add_counters` (Imp's Mischief, Draining Whelk — no card
needed it); PAR-72's own two-step hand-reveal-then-choose primitive
(Acquisitions Expert, where the *hand's owner* rather than the caster picks
which cards get revealed); and the Horsemanship/Banding batch's own five
residual cards — `Nature's Blessing` (an "instruction A, or `<creature>`
gains X instead" alternative-effect body), `Tolaria` (a new "activate only
during any upkeep step" RULE 602.5d timing-restriction marker, threading
through five engine files for one card), `Urza's Avenger` (a modal "your
choice of `<kw1>`, `<kw2>`, …" keyword-choice grant with no existing
interactive-choice primitive), `Wall of Caltrops` (a board-state
conditional trigger counting blockers by creature type), and `The Girl in
the Fireplace` (the Horsemanship-flavoured sibling of the ~60-card "create
a *named* token, then a follow-up sentence grants it a quoted ability"
family `Master of the Hunt` was hand-authored around rather than built as
shared grammar). `Oddric, Lunar Marquis`'s own 11-ability "the same is
true for changeling, devoid, fear, flanking, horsemanship, ingest,
intimidate, landwalk, shroud, tantrum, wither, …" cluster is shared
residue between the Horsemanship and Banding batches.

## Two tracks: basic mechanics vs. set-specific mechanics

The tail isn't one undifferentiated pile — every unclaimed template falls
into one of two tracks, and they get worked by two different prioritization
rules, not one:

- **Basic mechanics** — an oracle-text *shape*, keyword-action, or template
  that recurs across many sets and years (a modal wrapper, a P/T
  characteristic-defining ability, an O-Ring variant, a targeted-destroy
  compound, or a keyword *action* like Investigate/Explore/Scry that a
  design team keeps reprinting set after set once it exists). Worked by raw
  cache-wide yield (`parser_probe.py rank`/`blocked`) — a fix here keeps
  paying off on sets not yet printed, so the biggest SOLO count wins
  regardless of which deck happens to need it today. This is the default
  track and where most of this document's worked examples live. The
  raw-cache `rank`-driven pass was exhausted 2026-08-28, but re-entering
  through `commander_tail_report.py`'s own Bucket B histogram found a
  second wave of real wins the same day 2026-09-15 swept through
  (PAR-78/PAR-79 alone are 65- and 105-card clusters, see `BACKLOG.md`) —
  don't copy "exhausted" forward without re-running the tool.
- **Set-specific mechanics** — a RULE 702 keyword *ability* or *action*
  that a design team built for, and largely confined to, **one expansion or
  Commander-precon product line** (it may get one or two nostalgia reprints
  years later, but no ongoing set keeps printing new cards with it). A fix
  here only pays off for decks actually built around that product — so it's
  worked **deck-first**: when auditing a saved deck whose commander (or the
  deck itself) comes from a named set/precon, check that set's own
  signature mechanic(s) against the table below *before* falling back to
  generic cache-wide ranking, since a single precon commonly clusters a
  dozen+ of its own set's cards into one saved deck.

  A mechanic only belongs in this table once someone has actually run
  `parser_probe.py blocked "<its regex>"` and confirmed real cards are
  blocked on it — a name alone (guessed from a set's marketing copy) isn't
  worth an entry; verify, then add the row. Extend this table as each
  deck's audit turns up its set's mechanic, rather than trying to
  pre-populate every named product's keyword in one pass.

  | Mechanic | RULE | Set / product | Status (as of date checked) |
  | --- | --- | --- | --- |
  | The Ring tempts you | 701.51/701.52 | Tales of Middle-earth | **Done** — `Player.ring_level`/`ring_bearer_id` (`Done_Backend.md`, cEDH-cube batch); the oracle-text clause itself and "whenever the Ring tempts you, `<effect>`" (`EventType.RING_TEMPTED`) followed later (2026-08-05) |
  | The One Ring's own bespoke clauses (protection-from-everything-on-cast, burden-counter life loss, burden-counter draw scaling) | — | Tales of Middle-earth (one unique card) | **Partially done** (checked 2026-08-05) — "burden" is now a recognized named counter kind, but the card's other two clauses are still unclaimed; likely hand-authoring territory (RULE 122.1a's burden-counter card is a singleton, not a cluster) |
  | Frodo, Adventurous Hobbit (this deck's own commander) | — | Tales of Middle-earth | **Done** (2026-08-05) — `GameState.life_gained_this_turn` (new per-turn tracker) + `EffectSpec.condition`'s `"is_ring_bearer"`/`"ring_tempted_at_least"` keys, `effects.ConditionalEffect._condition_holds` generalized to AND multiple condition keys together. The same `"is_ring_bearer"` key also closed Aragorn, Company Leader/Faramir, Field Commander's "if you chose a creature other than ~" clause (each still has one unrelated second gap of its own) |
  | Frodo, Sauron's Bane (the same DFC's back face) | — | Tales of Middle-earth (one card) | **Done** (2026-08-05) — hand-authored in `ability_catalogue.py`, no new engine primitive after all: a two-step RULE 613.6 standing conditional static driven by a plain custom counter, `ActivationCost.activation_condition` settable straight off a hand-authored `cost` dict, and a new `ConditionalEffect.ring_tempted_at_most` + `grant_triggered_ability`'s own `grant_effects` honouring a per-entry `condition` for the "…otherwise…" branch — see `Done_Backend.md`'s "Frodo, Sauron's Bane" entry |
  | Choose a Background | 702.124 | Commander Legends: Battle for Baldur's Gate | **Done** (2026-08-05) — bare FLAG keyword, inert in-game like Partner; the deckbuilding pairing check itself is [BACKLOG.md](BACKLOG.md)'s DB-3, still open |
  | Magecraft | ability word | Strixhaven | **Done** — `segmenter._MAGECRAFT_RE` |
  | Amass / Mutate / Monstrosity / Adapt / Goad / Bargain / Fading / Soulbond | 701.x / 702.x | War of the Spark / Ikoria / Theros / various | **Done** — see `Done_Backend.md`'s cEDH-cube batch |
  | Day/Night (werewolf transform) | 702.28 (2011+ template) | Innistrad: Midnight Hunt/Crimson Vow | **Done** — the *legacy* pre-2021 template is the one accepted non-goal above |
  | Specialize | digital/Alchemy (no paper CR) | Alchemy Horizons: Baldur's Gate | **Partially done** (2026-09-03, MEC-48) — `catalogue/keywords.py` recognizes a bare "Specialize {cost}" line; `effect_binder._specialize_activated_ability` binds it to a real sorcery-speed "{cost}, Discard a card" activated ability whose body is `SpecializeEffect` (a persistent `GameObject.is_specialized` designation + `EventType.SPECIALIZED` — **no** characteristic swap; the five per-colour specialized faces aren't in this repo's Scryfall seed, documented simplification); `segmenter._TRIGGER_VERBS` gains "specializes" → `SPECIALIZED`. +6 bare-cost cards (Gale/Jaheira/Rasaad/Vhal/Viconia/Wilson) + several specialized faces whose "when ~ specializes, `<modeled effect>`" body now parses. **Still open:** the "Specialize {cost}. `<rider>`" cards (cost-reduction / "activate only if" / alternate-zone riders) are held UNMODELED by `_SPECIALIZE_WITH_RIDER_RE` — each rider is its own small activated-ability-modifier follow-up (~5 cards: Imoen/Karlach/Shadowheart/Lukamina/…). |
  | Starting intensity | Duskmourn's Room-adjacent template | Duskmourn: House of Horror | **Not done** (checked 2026-08-05) — 0 cards SOLO-blocked on the phrase alone (always paired with another unclaimed clause); needs its co-blocker identified before estimating real scope |
  | Learn (Lessons) | 701.50 | Dominaria / Strixhaven | **Partially done** (checked 2026-08-05) — bare "Learn." is a 7-card SOLO cluster; the Lesson-sideboard-zone infrastructure itself (RULE 701.50a "look at your sideboard") isn't built, so a full deck with real Lessons stays out of scope regardless |
  | Investigate | 701.19a | Shadows over Innistrad (**reused across many later sets** — belongs on the *basic* track, listed here only as the worked example that motivated this split) | **Done** (2026-08-05) — a `create_token` alias onto the already-shipped Clue token, 87+ cards in one row; this is the case study for "keyword action, but basic not set-specific" — check *reuse breadth* before filing something here |
  | Station | 702.184a / 721 | Edge of Eternities | **Done** (2026-08-27) — a third "striated text box" grammar alongside Leveler/Class (`catalogue/station.py`), the reminder-line activated ability bound structurally off Scryfall's own `keywords: ["Station"]` entry (`effect_binder._station_activated_ability`); see `Done_Backend.md`'s Station entry |
  | Horsemanship | 702.31 | Portal (Portal-only, no reprints since) | **Done** (MEC-87, 2026-09-15) — `combat.has_horsemanship` wired into `can_block`; +30 cards via five parser handlers. See `Done_Backend.md`'s "Horsemanship" entry |
  | Banding | 702.22 | Alpha/old-border era | **Done** (MEC-88, 2026-09-15) — `combat.has_banding` + RULE 702.22j's damage-assignment reroute; +9 cards (parser + one hand-authored singleton). RULE 702.22c's interactive attacking-band declaration stays unbuilt (no MODELED card exercises it) and five residual cards remain, each blocked by an unrelated template gap — see `Done_Backend.md`'s "Banding" entry and this file's own Commander-legal tail sweep section above |
  | For Mirrodin! | 702.90-adjacent | New Phyrexia | **Recognition fixed** (PARSER_VERSION 101, PAR-28) — the trailing-`!` keyword line is now claimed (`_KEYWORD_TOKEN_RE`); no engine behaviour (Living Weapon-style germ token) yet |
  | Max Speed / Start Your Engines! | RULE 702.178 / 702.179 | Aetherdrift | **Done** (PARSER_VERSION 101, PAR-28) — full Speed subsystem: `Player.speed`, the Start-Your-Engines! SBA, the RULE 702.179d life-loss inherent trigger, `your_speed_is_max` static gate. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Job Select / Tiered / Increment / Paradigm / Teamwork / Sneak | various | Final Fantasy | **Not done** (checked 2026-08-27) — recognized-but-inert; Sneak's name also collides with an unrelated hand-authored effect, worth disambiguating before building. (**Power-up** was in this row — now **done**, PAR-28) |
  | Space Sculptor | — | Warhammer 40,000 (Commander) | **Not done** (checked 2026-08-27) |
  | Living Metal / More Than Meets the Eye | — | Transformers (Commander) | **Not done** (checked 2026-08-27) |
  | Web-slinging | — | Spider-Man | **Not done** (checked 2026-08-27) |
  | Firebending / Mobilize | 702.189 / 702.181 | Avatar: The Last Airbender / Tarkir: Dragonstorm | **Recognition done, behaviour not** (PARSER_VERSION 100, PAR-27) — "Firebending X, where X is …" / "Mobilize X, where X is …" no longer drops the card to `UNMODELED` for a formatting reason (the keyword line is claimed, inert — same as a plain "Firebending 2"); the variable-N token/damage behaviour is still unbuilt |
  | Infinity | — | (product TBD at audit time) | **Not done** (checked 2026-08-27) — 0-2 cache hits |
  | Warp | 702.185-adjacent | Bloomburrow | **Not done** (checked 2026-08-27) — distinct from the unrelated "Warp" collision noted for the Final Fantasy row above; verify regex scoping before building either |
  | Exhaust, Solved, Boast, Forecast | RULE 702.177 / 702.169 / 702.142 / 702.57 | Edge of Eternities / Murders at Karlov Manor / Kaldheim / Dissension | **Done** (PARSER_VERSION 101, PAR-28) — the whole "Keyword — `<ability>`" label family bound with its real restriction (Exhaust/Power-up once-per-game, Boast attacked-this-turn + once-per-turn, Forecast from-hand + upkeep-only, Solved's Case solve state machine). Per-card oracle coverage of individual Cases is still long-tail (an unbuilt "N …this turn" solve-condition tracker, or an effect-body gap in a `Solved —` clause) — the *mechanism* is done, same standing as the battle pool. See `Done_Backend.md`'s "Keyword — [ability] families" entry |
  | Mayhem, Decayed | various | Duskmourn: House of Horror | **Not done** (checked 2026-08-27) — Decayed also has real combat-restriction implications (can't block, 2 damage then sacrifice), not just a cost/cast wrapper |
  | Double team (+ Conjure / Draft from a spellbook / Boon / perpetual) | — (Alchemy digital keyword, no CR RULE 702 number) | Alchemy Horizons: Baldur's Gate / Dominaria | **Not done** — noted by PAR-27's keyword audit (2026-08-28): "Double team" is absent from `catalogue/keywords.py`'s CR-scoped `_TABLE`, so "Flying, double team" / "Menace, double team" lines fail `is_keyword_line`. ~18 cache cards, all also-blocked on other unmodelled Alchemy mechanics (Conjure/Draft/Boon/perpetual). Recommend deciding the whole Alchemy keyword family as one unit (likely a non-goal like Vanguard — Alchemy cards aren't paper-Commander-legal, so they're outside the `--commander-legal-only` coverage scope anyway) rather than adding "double team" piecemeal |

  The rows above come from a 2026-08-27 systematic audit of all 195
  registered `parser/oracle/catalogue/keywords.py` entries against real
  `game/` consumers (not just cache LIKE-counts) — see `BACKLOG.md`'s
  `PAR-22` through `PAR-26` for the audit's full findings, including the
  **evergreen** gaps it found alongside these set-specific ones (Prowess,
  Affinity, Delve, Shroud, and a dozen others — those belong on the
  *basic* track, not this table, since they recur every set rather than
  being confined to one product). Several of the rows above are still first-pass
  cache-count estimates (0-2 hits at audit time, not yet `parser_probe.py
  blocked`-verified per this section's own rule) — verify before sizing a
  build, don't just copy the status.

  Doctor's companion / Time travel (Doctor Who), Augment (Aether Revolt),
  ki counters (Kamigawa block), and whatever Lorwyn Eclipsed/New
  Capenna/further Bloomburrow-block sets turn out to print as their own
  signature mechanic are all **known-unverified** — real cards may be
  blocked on some of these phrases (see `rank`'s live output), but nobody
  has yet confirmed scope/primitive-existence for them the way the rows
  above were. Don't copy a status onto this list without running the
  check yourself.

## Known-open clusters

### PAR-132 calibration: dependent bodies around an already-complete target scope

PAR-130 completed the `that player controls` scope itself: event, per-player and prior-target
antecedents now reach trigger, spell and activated-ability targeting. The cards still blocked in
that search are separate body/referent families, bundled as PAR-132 rather than left as false
PAR-130 residue:

- a `choose [up to] one target …, then` announcement followed by a chosen-object body (Decoy
  Gambit, Mega Flare, Shellshock, Disorienting Choice, Guff Rewrites History, Vaevictis Asmadi,
  Kitesail Larcenist);
- follow-ups over the selected set or objects affected "this way" (Elminster's Simulacrum,
  Hideous Taskmaster, Riptide Gearhulk, Luminate Primordial, Juvenile Mist Dragon, Olinda,
  Sontaran General, Sylvan Primordial, King Solomon's Frogs, Unexplained Absence, Demonic Junker,
  Battle at the Helvault);
- prior-target group bodies beyond the now-shipped two-target controller validation (Alpha Brawl,
  Deputy of Detention, Legions to Ashes; Down for Repairs additionally names an Attraction);
- missing trigger heads around otherwise-supported bodies: beginning of combat on each opponent's
  turn, a Dragon becoming a target, damage thresholds, defending-player combat damage, and damage
  from an instant or sorcery spell;
- sequence-local `that much` operands outside a firing event, the quoted-grant wrapper on Commando
  Raid, and finite/permanent-control durations tied to the source remaining on the battlefield
  (Sower of Temptation, Master Thief, Dragonlord Silumgar, Mind Flayer, Possession Engine, Giant's
  Grasp, Rangers of Ithilien).

Each row must be re-sized before implementation; this list records shared shapes and examples, not
a promise that every named card has no second blocker.

Long-tail residue that no open ticket names — salvaged when the per-version
changelog was removed, because most of it had been filed under `PAR-30`,
`PAR-60`, `MEC-77` and the Clash/Airbend bullets, **all since closed**. None of
it is schedulable as written; it is sizing material for the next pass, in the
same spirit as the worked examples below.

**Verified against the v298 ledger on 2026-09-09** — every row below is a card
that is `unmodeled` *today*, and the blocker quoted is its **actual** remaining
unclaimed clause, not the description its original batch wrote. That check
mattered: of the 61 cards the changelog listed as open, **25 were already
`MODELED`** and eight whole clusters had closed underneath their own notes —
the threaten/gain-control family (Broadcast Takeover, Call for Aid, Furnace
Reins, Loki's Scepter, Flayer of Loyalties, Goatnap, Awaken the Sleeper), the
O-Ring two-sentence templating (Oblivion Ring itself, Crack in Time, Driftgloom
Coyote, Food Coma, Brutal Cathar), dynamic Incubate (Excise the Imperfect,
Sunfall), colour-filtered targeting (Combust, Snow Hound, Tidebinder Mage,
Offspring's Revenge), `normalize`'s legendary short names (Kaalia of the Vast,
Owlbear Cub, The Vast Scrier), "tapped and attacking" (Winota, Kari Zev),
majority/permanent vote ballots (Council Guardian, Council's Judgment), and the
RULE 508.1g attack-tax opt-out (built in v288). Two more entries named a
blocker that had been fixed while the card stayed unmodeled on something
unrelated. **Re-run this check before sizing anything below** — that is this
document's own standing rule, and it has now caught itself.

| Cluster | Still open | Cards |
| --- | --- | --- |
| Becomes-target self-sacrifice | "sacrifice it **unless you discard a land card**"; the quoted-ability grant forms (`… has "when ~ becomes the target of a spell or ability, …"`) | Cursed Monstrosity · Crystalline Nautilus, Dismiss into Dream, Boneshard Slasher, Makeshift Mannequin |
| Quoted-ability grant until EOT | the compound "gets +2/+0 **and** gains '…'" wrapper | Demonic Gifts |
| Return-to-battlefield destination | "return it to the battlefield **face down**", and its flipped/transformed siblings | Ashcloud Phoenix, Homura Human Ascendant, Loyal Cathar |
| Mass graveyard return, riders | riders on the returned cards (an extra counter, "each of them is a 1/1 Spirit"); "…that weren't put there this way" | Pyrrhic Revival · Storm of Souls · Bringer of the Last Gift |
| Distribute counters + tail | "distribute N +1/+1 counters among 1, 2, or 3 target creatures, **then** …" and the post-distribute "each of those creatures" tail | Biogenic Upgrade, Court of Garenbrig |
| Counter doubling, union target | "double the number of **each kind of** counter on target **artifact, creature, or land**" | Vorel of the Hull Clade |
| Land destruction, search tails | the "…each player searches…" / "…that land's controller searches…" follow-up after the destroy | Field of Ruin, Demolition Field, Magmatic Hellkite |
| Loses-all-abilities + base P/T | "loses all abilities and becomes a `<colour>` `<type>` with base power and toughness N/N"; the front-loaded "until end of turn, … has base P/T … and gains `<kw>`" form | Turn to Frog, Snakeform, Ovinize · Creeperhulk |
| Cost reduction gated on the target | "this spell costs {N} less to cast **if it targets** a creature (card) with mana value N or less / with a +1/+1 counter on it" | No One Left Behind, Revoke Demise, Titanic Brawl |
| Un-limited batch-death triggers | "whenever **1 or more** other creatures [you control] die, …" with no "only once each turn" limiter to collapse the per-object firing into the right net | Great Fierce Bee, Vengeful Townsfolk |
| Halved, rounded X | "you gain **half X** life and draw **half X** cards. round down each time" | Hydroid Krasis |
| "destroy ~ unless you pay" follow-up | "**if ~ is destroyed this way**, …" | Cosmic Horror |
| Random modal + emblem body | "choose 1 **at random** —", plus an emblem whose own body is unclaimed; "you may planeswalk" (only the bare "planeswalk" fullmatch exists) | Seek Bolas's Counsel · Start the TARDIS |
| Threaten after-tail | "…**create a Blood token**" after the gain-control / untap / haste sequence | Bloody Betrayal |
| Saddle referent | "whenever ~ attacks **while saddled**, choose a nonlegendary creature that saddled it this turn" | Calamity, Galloping Inferno |
| Compound attack-trigger conditions | "whenever ~ attacks, **if** a nonland permanent left the battlefield this turn **or** a spell was warped this turn, …" | Alpharael, Stonechosen |
| Misc singletons | "another target creature" (the `other_creature` kind is not engine-wired); "**if it was a Gideon planeswalker**" conditional tail | Arwen, Mortal Queen · Gideon's Defeat |
| Unread activation-cost fragments (ENG-51 residue, v500) | an activated line whose cost `catalogue/cost_text.scan_cost_text` doesn't read completely stays unclaimed: three-colour sacrifices ("a red creature, a green creature, and a white creature"), "of the chosen type", "untap N tapped creatures you control", "exile 1 or more …", "sacrifice ~ and a creature you control", "discard a card with mana value X", an Aura/Equipment "attached to ~"; plus Un-set and Alchemy one-offs | the Herald cycle · Doom Cannon · Halo Fountain · Corpseweft · Great Hall of Starnheim · Knollspine Invocation · Faunsbane Troll |

## Lessons that keep recurring

Each was paid for once; re-reading them is cheaper than re-learning them.

- **A row that reads a pronoun as the source is *wrong-but-MODELED* the moment a trigger's subject is
  a group — audit the covered set, not just the unclaimed one (PAR-123, v552).** `_SELF_SUBJECT`
  folds "it" in with "~", `_pay_cost_then_general` parsed its branch with `self_subject=True`, and a
  keyword grant after a "~" sentence stamped the firing object: each *claimed* a group-trigger clause
  and acted on the wrong permanent (Fearless Fledgling flew the land, "you may pay {1}. If you do, it
  gets +1/+1" pumped the Enchantment). No failing test and no unclaimed clause points at one. What
  found them: (1) instrument `parse_effect_body` for group-flag failures to list the *unclaimed*
  ones by verb, (2) scan every **modeled** card whose group-trigger body has a bare pronoun and no
  referent evidence in its specs (`__group_subject__` / `previous_subject` / `remembered` / a
  `trigger_subject_referent`), (3) the completion test — a clause whose "target creature" spelling
  parses must parse in its group form. Fix the mechanism once (a generic seed + a targeted-spelling
  wrapper), not one row per verb; and expect stale pins: three tests recorded the gap as "still
  unmodeled".
- **A fallback that generalizes a whole grammar must leave the specific rows first — and its
  wrappers must not sit outside a body that runs later.** The group fallback is tried only after
  every row declined, and it refuses any body whose effect runs after the trigger's event window
  closed (a payment's "if you do", a "you may", a delayed trigger): those read the *remembered*
  object instead. A wrapper hiding a second target would also have announced none.

- **`commander_tail_report.py`'s Bucket-D "missing primitive" label is a
  heuristic, not proof — grep `game/` before filing a `MEC-*` ticket.** The
  2026-09-15 sweep found several Bucket-D flags where the primitive already
  existed and only parser recognition was missing: RULE 613.4d's
  `pt_switch` layer static, the `unblockable`/`temp_unblockable` grant, and
  the "all"-amount `prevent_damage_shield` — each filed as a `PAR-*` ticket
  instead of the `MEC-*` the report suggested. Bucket D caught two of its
  own labels the same way on closer inspection ("no dice subsystem at
  all", "ISA gap: meld" — a dice subsystem and meld had both already
  shipped, `MEC-75`/`MEC-77`), narrowing what the sweep actually needed to
  file down to `MEC-90`'s missing amount-referent and a small meld-trigger
  widening folded into `PAR-92`.
- **Decompose into atomic grammar units — don't enumerate phrase variants.**
  Now a standing rule, not just a lesson — see the extend-parser skill's
  `reference/handler-recipe.md` for the full writeup and the test to apply
  before adding a row. The short version: a template usually varies along
  more than one axis (subject/type/color, count, exception, duration); the
  fix belongs at the axis, in a shared primitive
  (`subgrammars.py`, `static_handlers.object_filter`, a
  `catalogue/keywords.py` word table), not as a regex/whitelist row keyed to
  the one search phrase or card that motivated it. This was learned the hard
  way, as a **mid-batch correction**, twice: PAR-78 (v393) started a closed
  per-phrase source-colour word list, then replaced it with a fix to
  `static_handlers.object_filter`'s general OR-split instead; PAR-79 (v401)
  did the identical thing for a subtype-target list, and the fix's own scope
  leak — it also covered two cards outside PAR-79's own search phrase — was
  the tell that the row it almost became was never really a one-off. Neither
  correction was caught at design time; both were only visible once the
  closed list was already growing. A third instance (v408) wasn't even
  mid-batch — it was a standing-code audit, prompted by a question about why
  PAR-79 kept needing new increments at all: two of its own already-shipped
  rows (`_CANT_BE_BLOCKED_TURN_OTHER_ATTACKER_RE`/`_LEGENDARY_RE`, each
  correctly built and tested in its own increment) turned out to be exactly
  the enumerate-phrase-variants shape this lesson warns about, once
  `object_filter` learned to strip a leading "attacking"/"legendary" flag
  word itself — at which point both rows were a strict subset of the general
  filter row and deleted, +0/+0 coverage (a code-quality fix, not a new
  handler). The generalizable tell doesn't only show up while writing a
  batch; it's worth asking of *already-shipped* rows in a search-phrase
  ticket too, not just new ones.
- **"Still open" notes written inside a shipped batch's narrative go stale
  silently, and nothing points at them once the batch's ticket closes.** The
  removed per-version changelog ended most entries with a residue list ("still
  open in this cluster: …"). Those lists were the only record that those gaps
  existed — but they were filed *under the version that closed something else*,
  so when `PAR-30`, `PAR-60` and `MEC-77` closed, the residue kept no home and
  nobody re-checked it. Auditing the 61 cards named that way on 2026-09-09
  found **25 already `MODELED`**, eight clusters wholly closed, and two entries
  whose named blocker had been fixed while the card stayed unmodeled on
  something unrelated. This is `CLAUDE.md`'s no-half-implementations rule seen
  from a third angle: not a deferred item rolling over, but a *recorded gap
  losing its owner*. Residue belongs in a place someone re-reads (`BACKLOG.md`,
  or this file's *Known-open clusters*), never as a trailing sentence on a
  worklog entry.

- **A ranked template that is a block *wrapper* (modal, Saga, Class level) is
  usually a red herring.** `gate.py` fail-closes the whole block when any one
  mode body fails, appending *every* body to `unclaimed` — so the wrapper
  shows up in the ranking as a proxy for "some sibling clause still has a
  gap". Re-derive which sub-clause actually fails before trusting a
  template's face-value card count.
- **The all-or-nothing coverage gate makes every batch-plan estimate an
  overcount.** Most cards blocked by a template have *other* unclaimed
  clauses too. A family whose primitive is correct and tested can still
  yield literally zero newly-covered cards.
- **A plan-doc row's own framing can be wrong.** Escape/Kicker/Multikicker
  were documented as "new keyword mechanics" but were already fully modeled
  — the real blockers were two recognition bugs. Sample real cards before
  accepting a stated scope.
- **When a handler's regex has a subject alternation, check every
  alternative is actually read out.** `_lose_life` and later `_discard` both
  matched "target player …" but never threaded `target_kind` through, so
  both silently applied the effect to the source's controller instead.
- **When a general regex fix passes the happy path, write the adversarial
  "why doesn't this over-match" test before trusting it.** A general
  keyword-line split looked correct until `"flying, then draw a card"`
  caught it; it was replaced with a narrow closed list.
- **Parse-only tests aren't enough — write execute tests.** Two shipped
  effect families passed the whole suite yet crashed on first real use
  (`Zone` imported under `TYPE_CHECKING` only; `legal_targets` missing a
  branch and silently returning `[]`). Also: new selector params must be
  whitelisted in `effects._SELECTOR_KEYS`, or they are silently dropped.
- **A ticket that reads as "N more rows in a whitelist" is worth
  re-measuring before you write the rows.** MEC-14 listed four condition
  phrasings as four independent entries; the biggest of them turned out not
  to be a new *kind* at all but a new **subject** ("as long as *enchanted
  permanent* is a creature" is about the Aura's host, not the Aura), and one
  `of` key made every existing kind work on that subject for free. Two of
  the other three then needed no more than the row the ticket predicted. The
  general lesson: when several ticket items share a shape, look for the
  axis they vary along before adding one entry per item.
- **"Needs a new primitive" is worth re-checking against the phrasing.**
  MEC-14's soulbond item was blocked on nothing at all in the engine — the
  ``soulbond_pair`` selector had shipped with the cEDH cube batch and simply
  had no oracle phrase that could reach it. Three parser rows closed it.
  This is the same failure mode `CLAUDE.md`'s batch-discipline rule
  describes, seen from the other end.
- **Ticket card estimates are wrong in both directions, and the wrong
  *shape* is the expensive kind.** MEC-12(a) described a variable target
  count as "Death Kiss, 1 card". Death Kiss really is the only card with
  that phrasing — but four *other* cards print "for each opponent, goad up
  to one target creature that player controls", which is the same feature
  with an already-shipped constraint (`distinct_controllers`) doing the rest.
  Measuring the *mechanism* rather than the quoted phrase turned a
  one-card item into a five-card one at no extra cost.
- **Scryfall's own `keywords` array is noisy — cross-reference before
  treating a raw string as a real keyword.** It mixes RULE 702 keyword
  *abilities* (what `catalogue/keywords.py` tracks), RULE 701 keyword
  *actions* (Mill/Scry/Investigate — a structurally different mechanism,
  ordinary verbs handled by `handlers.py`), created-token type names
  (Treasure/Food), and — the majority by distinct-string-count — one-off
  card-specific *flavor* ability names Scryfall's own keyword-extraction
  heuristic mistakes for a reusable keyword whenever a card prints the
  "Name — effect" ability-word template with a novel name ("10,000
  Needles", Jumbo Cactuar). A diff of "every distinct raw `keywords`
  string not in our registry" (2026-08-28) found 689 distinct strings —
  almost none of them a real registry gap; see `normalize.
  _strip_unregistered_keyword_labels` (PARSER_VERSION 99) for the fix this
  specific noise pattern led to.
- **At scale, "verify before sizing" can invalidate an entire `rank`
  top-N in one pass, not just one entry.** 2026-08-28 (was ticket PAR-20,
  now closed): six of the highest-count templates in a fresh cache-wide
  `rank` (40-240 raw hits each — "choose N —", "you get an emblem with
  `<name>`", "costs `<cost>` more … for each target beyond the first", the
  O-Ring "exile … until ~ leaves", "enchanted creature has `<name>`", the
  2011+ werewolf transform condition) were checked with `parser_probe.py
  blocked`, and *all six* turned out to already be fully claimed by
  existing grammar — every card's real blocker was a distinct, unrelated,
  one-off co-resident clause (`blocked`'s "what else blocks those cards"
  residue came back essentially all count-1). This isn't a one-off miss;
  it's a sign the basic-mechanics (cache-wide) track's easy big wins are
  genuinely thinning out at the current coverage level (~35.5%), not just
  a bad `rank` run. The one discrete win squeezed from that residue
  afterward — RULE 604.3's "power and toughness are each equal to the
  number of `<X>`" CDA-P/T handler (PARSER_VERSION 105, +20 cards) — was
  the exception that proves it: a genuinely unrecognized shape, but a
  narrow whitelisted one, not a big generic family. When this happens,
  don't keep re-running `rank` hoping for a better top-N — switch to the
  deck-first track instead (a real saved deck's cards are far more likely
  to share an actual unfixed pattern than the whole-cache aggregate is at
  this point).
- **"Coverage" and "actually playable" are two different claims — check
  both.** Three separate PAR-6..10 (2026-08-03) cards were already
  `MODELED` (the coverage gate satisfied) while being functionally inert: a
  bare Cycling keyword was claimed but bound to no real activated ability
  (PAR-9); a layer-6 grant reaching the *hand* zone populated
  `granted_activated_abilities` correctly, but `legal_actions`' hand-zone
  loop only ever scanned `activated_abilities`, so the granted one was
  never offered (PAR-8); and `can_activate` had no branch at all for an
  ability sourced from the *graveyard* zone, so a new "return this card
  from your graveyard to the battlefield" effect would have been unusable
  the moment it shipped (PAR-10). None of these show up in a coverage
  diff — only playing the card (or writing an execute-level test that
  calls `legal_actions`/`can_activate`, not just `bind_from_catalogue`)
  catches them. Grep for the *offering* code path, not just the binding
  one, whenever a new effect targets a zone/ability-list combination
  nothing has used yet.
- **A ticket's own example can be hiding a much bigger, unrelated family
  one clause away.** PAR-10 was framed as "Jin-Gitaxias's compound
  activation condition" (a handful of cards). Sizing its SOLO list turned
  up Dread Wanderer blocked on a *second*, wholly unrelated clause: "Return
  this card from your graveyard to the battlefield[, tapped]." was
  entirely unrecognized — 69+ cache cards, by far the batch's biggest win,
  found only by running `blocked` on the literal phrase inside a
  "ALSO BLOCKED" card's *other* unclaimed line rather than stopping once
  the ticket's own named clause was handled.

## Worked example: the battle pool (RULE 310)

The battle *card type* is fully implemented (see `Done_Backend.md`,
"Card-type & structural coverage"), which makes this pool a clean sample of
what the tail is actually made of: **12 of 39 cached battles are MODELED**,
and the other 27 fail on ordinary effect-body grammar with nothing to do with
battles as a type. Grouped by what each actually needs, most-cards-first:

- **"you may `<cost>`. If you do, `<effect>`."** — Occupation of Kulrath,
  Invasion of Mercadia, Invasion of Ergamon. **The engine primitive already
  exists**: `RulesEngine.request_pay_cost_then` (RULE 118.3, built for Mana
  Vault and the Pacts, with an "if you don't" branch). This is a *parser
  handler only*. Do not re-defer it as "needs a primitive" — highest-yield
  item here and the natural next one to take.
- **"search your library and/or graveyard"** — Invasion of Ikoria, Invasion
  of Arcavios (the latter also "outside the game"). Same blocker as the
  Doomsday/Finale entry; closing that closes these.
- **Multi-target "up to N target creatures each get …"** — Invasion of
  Kylem. `TargetSpec.count` already models N≥2 for destroy/exile/damage; the
  pump family is still N=1-only.
- **Mass damage with a compound selector** — "each creature **and each
  planeswalker**", Invasion of Karsus. The selector damage handler takes one
  selector, not a union.
- **X-scaled token creation** — "create X 2/2 … tokens", Invasion of New
  Phyrexia. `COUNT_X` exists as a fragment; the create-token handler doesn't
  use it.
- **The bespoke tail, one card each** — hand-authoring territory rather than
  parser work: stun counters (Kamigawa), "for as long as that card remains
  exiled, its owner may play it" (Gobakhan), "exile all cards from your hand,
  then draw that many" (Kaldheim), manifest (The Battle of Dragon Brothers),
  reflexive "when you do" triggers (New Capenna, Tarkir), fight-after-counter
  (Muraganda), "isn't exactly two colors" (Ravnica), power-X-or-less destroy
  (Lorwyn), "nonbattle permanent card" (Tolvada), scry-then-conditional-draw
  (Pyrulea), "sacrifices a creature or planeswalker of their choice" (Azgol),
  dig-until (Alara), a modal "choose one or both" ETB (Fiora), a phase
  trigger on "your combat step" (Occupation of Llanowar),
  search-for-a-typed-card-to-hand (Theros), look-at-top-N-reveal-one
  (Ixalan), and multi-clause mill/discard/draw (Amonkhet).

**What this sample shows.** One line of shared grammar —
`normalize._SELF_REFERENCE_RE` folding "this battle"/"this Siege" to `~` —
moved the pool 0 → 12, while the *card type* work itself moved it zero. The
gains that matter are almost always in shared grammar, and a fully
implemented mechanic is no guarantee its cards parse.

## Worked example: dungeon rooms (RULE 309)

Same lesson from the other direction: the RULE 309 dungeon engine and all
four room graphs (`game/dungeons.py`) were fully built while sitting at
21/30 modeled rooms — nothing dungeon-specific was missing, only ordinary
effect-body grammar (`room_effect_specs` runs the exact same
`segmenter.parse_effect_body` a card's own text does). PAR-13 (2026-08-04)
closed 8 of the 9 gaps: a P/T-delta route for `grant_until` plus its
"can't attack/block until `<duration>`" sibling (Fungi Cavern/Twisted
Caverns — both also picked up real non-dungeon cards via two new `_GROUP`
phrasings); a mandatory compound discard-then-triple-sacrifice handler
(Oubliette); a legendary named token (Cradle of the Death God — the first
`Card.is_legendary` a synthesized token ever carried); `ImpulsiveDrawEffect`'s
first oracle-text route, previously hand-authored-only (Runestone Caverns);
a new `DrawRevealCastOneFreeEffect` + a `"cast_free"` `choose_objects`
action, the first hand-zone pick that chooser ever offered (Mad Wizard's
Lair); and a new mass-interactive primitive, `RulesEngine.
request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
single-player `request_pay_cost_then`) for "each player loses N life
unless they `<pay cost>`." (Veils of Fear/Sandfall Cell — the latter also
needed a new compound `ActivationCost.sacrifice` value,
`creature_artifact_or_land`, since the plain single-word sacrifice grammar
can't express an OR of three types).

**Throne of the Dead Three** ("Reveal the top ten cards of your library.
Put a creature card from among them onto the battlefield with three +1/+1
counters on it. It gains hexproof until your next turn. Then shuffle.")
is the one room left unmodeled — a genuine "reveal top N, choose one
matching a filter, place it with counters, shuffle the rest back" shape,
confirmed to have zero non-dungeon cache siblings (unlike every other gap
above, so there's no shared-grammar win waiting behind it). Left as an
honest residual rather than forced, the same call this document already
makes for the battle pool's own bespoke-tail cards.

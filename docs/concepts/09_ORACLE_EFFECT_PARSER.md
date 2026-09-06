# DeckLab: Oracle-Text → Effect Parser (Design)

Status: **design agreed, not yet implemented.** This is the plan for the
open "Oracle-text → effect *parser*" item in
[docs/implementation-state/BACKLOG.md](../implementation-state/BACKLOG.md) (Rules Engine,
Phase 2). It builds directly on the effect system already implemented in
[07_GAME_LOOP_EFFECT_SYSTEM.md](07_GAME_LOOP_EFFECT_SYSTEM.md) — read that
first; this document does not re-explain the effect hierarchy.

---

# THE GAP

The engine has effects but no way to *derive* them from a card. Concretely
(`../../backend/mtg_analyzer/game/rules_engine.py`
`_effects_for_spell`): an instant/sorcery resolves as a no-op unless a
fixture hand-attaches effects via the `spell_effects` hook. What's missing
is the single transformation:

```
oracle_text  ──►  [GameEffect]  attached to a GameObject
```

Everything downstream already exists: the four-type effect hierarchy, the
concrete one-shots (`DealDamage`, `DrawCard`, …), the `EffectRegistry`
(`type` + `params` → `GameEffect`), the event bus, replacement/trigger
machinery, and the `GameObject` ability lists that hold them.

---

# CORE ARCHITECTURE: A TWO-STAGE COMPILER WITH AN IR

Do **not** parse text straight into `GameEffect` objects. Split into a
**front-end** (English → data) and a **back-end** (data → engine objects),
with a serializable intermediate representation between them:

```
oracle_text ──► [FRONT-END: parser] ──► AbilitySpec[]   (pure JSON data)
                                             │  cached · versioned · validated
                                             ▼
                        [BACK-END: binder] ──► GameEffect objects on a GameObject
                                             │
                                             ▼
                                    existing RulesEngine (unchanged)
```

Why the IR is not ceremony:

1. **It is the security boundary.** Nothing derived from card text ever
   becomes code. The front-end emits only whitelisted `{type, params}`
   data; the binder only instantiates *known* `EffectRegistry` classes.
2. **It is the cache unit.** Parsing is expensive; the IR is cheap JSON to
   store and re-hydrate.
3. **It decouples "English is hard" from "rules are hard."** The parser
   can evolve regex → grammar behind the IR with zero `RulesEngine`
   changes. The front-end has **no `game/` imports** — pure, parallel,
   independently testable.
4. **It fails closed.** Unrecognized text never guesses and never crashes;
   it routes to a processing list (see the coverage gate).

---

# THE THREE DATA TIERS (durability model)

The most important structural decision. There are three tiers, and **the
link between a card and its effects belongs to none of them** — it is
*derived*.

| Tier | Lives in | Lifecycle |
|---|---|---|
| **Catalogue** (handlers) | **Repository, git-versioned** | Durable, curated, changes only by reviewed PR |
| **Card cache** | `backend/cache/` (gitignored) | Volatile, disposable, re-fetchable from Scryfall, clears on schema change |
| **The link** (`AbilitySpec[]`) | *derived* | A pure function of `(oracle_text, catalogue_version)` — regenerable, precious to neither store |

The consequence that drives everything: because the catalogue and the card
cache have **independent lifecycles**, the parsed link **must not be stored
inside the card row.** The card cache clears on a `card.py` schema change
but *not* when the catalogue improves — so specs baked into the card blob
would silently go stale every time a handler is added. The link cannot live
inside either store that produces it.

---

# THE INTERMEDIATE REPRESENTATION (`AbilitySpec`)

One ability = one spec. Pure JSON-serializable data; no behavior.

```jsonc
AbilitySpec {
  ability_kind: "spell_effect" | "triggered" | "activated" | "static"
              | "replacement" | "keyword",
  trigger?:  { event: EventType, condition?: { ... } },        // triggered
  cost?:     { mana?: "{2}{R}", taps_self?: true,
               sacrifice?: { ... } },                          // activated
  effects:   [ { type: "damage", params: { amount: 3 } }, ... ],// → EffectRegistry
  target?:   { kind: "creature" | "player" | "any" | "spell",
               count, restrictions },
  optional:  false,                                            // "you may"
  raw_text:  "deal 3 damage to any target",                    // provenance
  parser:    { version, source: "rule:<id>" | "manual",
               confidence }
}
```

`effects[].type/params` matches `EffectRegistry.create(type, params)`
exactly, so the binder is near-trivial for effects that already exist.
`trigger.event` maps to existing `EventType` constants
(`ENTERS_BATTLEFIELD`, `DIES`, `ATTACKS`, `LIFE_GAINED`, `SPELL_CAST`, …).

The `parser` provenance block is present from day one so hand-authored vs.
rule-matched specs are distinguishable without a data migration. (An
`"llm"` source was originally reserved for an ingest-time LLM tier — see
the decision below; that source value is unused.)

---

# THE CATALOGUE (handlers)

A **handler** is the unit of the catalogue: a **regex that identifies and
extracts**, paired with a **builder that emits an `AbilitySpec`** (data,
never executed behavior).

```python
Handler("damage") = (
    regex = r"deals? (?P<amount>\d+) damage to (?P<target>...)",
    build = lambda m: {
        "type": "damage",
        "params": {"amount": int(m["amount"])},
        "target": parse_target(m["target"]),
    },
)
```

## Form: declarative-first, with a code escape hatch

- **Declarative rows** — `{regex, effect_type, param_mapping}` committed to
  the repo — are the primary form and cover the templated majority. The
  interpreter is fixed code; rows only reference whitelisted
  `EffectRegistry` types through a constrained param-mapping. This is what
  keeps the analyzer safe (below) and makes the catalogue *a catalogue*.
- **Code handlers** — a hand-written escape hatch for genuinely irregular
  cards — live in the repo behind the same handler interface.

## Keyword abilities: the privileged fast-path handler class

**Keyword abilities are a closed, named vocabulary** — `Flying`,
`Trample`, `Deathtouch`, `Scry N`, `Kicker {cost}`, `Equip {X}`,
`Ward {cost}`, `Cycling {cost}`, `Annihilator N`, … — and they are the
cheapest, highest-confidence, and most *frequent* clauses in the game.
Treat them as a first-class handler class, not as free-text regex:

- **Two shapes.** Static/flag keywords (`Flying`, `Deathtouch`) map to a
  `keyword` `AbilitySpec` with no params. Parametric keywords
  (`Scry 2`, `Kicker {2}{R}`, `Equip {3}`) match a tiny fixed template and
  extract one param — a trivial, unambiguous sub-grammar.
- **Scryfall gives them for free.** Every card already carries a
  machine-readable `keywords` array
  (`../../backend/mtg_analyzer/models/card.py`
  `Card.keywords`). Use it to *anchor* the keyword pass: the array names
  which keywords are present, the catalogue supplies each keyword's spec
  (and extracts any parameter from the matching oracle line). This is a
  lookup, not parsing — near-zero cost and near-zero ambiguity.
- **They close the coverage gate fastest.** Because a handful of keywords
  recur across a large fraction of cards, building the keyword table first
  flips the most cards to `MODELED` per handler — it sits at the top of the
  "ranked by cards unlocked" roadmap. Segment and claim keyword spans
  *before* running effect-clause handlers, so the residue those handlers
  must cover is smaller.

A curated keyword catalogue (the ~150 evergreen + common keywords, each
mapped to its spec shape) is therefore Phase 1's cheapest, highest-yield
first deliverable.

## Versioning

`catalogue_version` is a **content hash of the catalogue files** (like
[`card_database`'s `_SCHEMA_SOURCE_FILES`](../../backend/mtg_analyzer/services/card_database.py)
hash). Because the catalogue is in the repo, the version is a natural
function of committed content. It triggers (a) the optional memo-cache
reconcile and (b) re-running the coverage gate over the cache.

---

# THE FRONT-END PIPELINE

```
oracle_text
  │ 1. NORMALIZE   strip reminder text (parens), lowercase,
  │                fold "three" → 3, singular/plural
  ▼
  │ 2. SEGMENT     split into abilities; peel the trigger/cost wrapper
  │                ("When X, <effect>", "<cost>: <effect>", keyword lists)
  ▼
  │ 3. MATCH       run the handler table over each *normalized effect clause*
  │                (NOT raw whole-card text) → AbilitySpec, capture-groups
  │                become params
  ▼
  │ 4. GATE        full-span coverage check (below)
  ▼
AbilitySpec[]   or   → processing list
```

Precedent for the style already in the tree:
[`../../backend/mtg_analyzer/game/mana_abilities.py`](../../backend/mtg_analyzer/game/mana_abilities.py)
— small regexes, normalized text, plain-data output, common cases covered,
long tail approximated.

## Factor shared sub-grammars — the rule that prevents explosion

"deal 3 damage **to any target**" / "**to target player**" / "**to target
creature or planeswalker**" are **one** damage handler with a **shared
target sub-grammar**, not three regexes. Same for numbers, "up to N", "you
may", durations. Without this factoring the regex set blows up
combinatorially and the coverage gate never closes. The damage handler
matches `deal N damage to <TARGET>`; `<TARGET>` is its own reusable
matcher.

**This rule is aspirational more often than it should be.** After 10+
card-pool batches, `parser/oracle/catalogue/subgrammars.py` — the shared
layer this section describes — holds a handful of helpers
(`resolve_target_kind`/`count_of`/`resolve_color_word`/
`resolve_spell_filter`); most handlers in `catalogue/handlers.py` still
hand-roll their own type-word lists, zone-name alternations, and
number-matching inline, because it's locally faster to write one more
regex than to go generalize a shared one under batch-yield pressure. That
debt is exactly what makes the parser brittle to "English is hard" instead
of robust to it — the same phrasing gotcha bites multiple handlers
independently instead of being fixed once. Two real examples from this
codebase's own history:

- **`normalize.py`'s spelled-number folding is global and blind to part of
  speech.** "put **one** onto the battlefield tapped and the other into
  your hand" (Cultivate) folds to "put **1** onto..." *before* any handler
  regex sees it, because normalize can't tell a numeral "one" from the
  pronoun "one." A handler written against the English word "one" silently
  never matches; a handler written against the folded digit works by
  accident, not by design. Every new handler must assume digit-folded text
  and check `normalize()`'s actual output on a real card during
  development — don't reason about the regex against the raw oracle text
  string.
- **`_peel_optional`'s "you may" stripping is positional, not general.** It
  strips a *leading* "you may " at each ability-body level (top-level
  spell, triggered-ability body, loyalty-ability body) before the body
  reaches `match_clause`. A "you may" appearing **mid-body**, after an
  earlier clause in the same sentence group ("Destroy target creature. You
  may search your library for a basic land...") is not recognized anywhere
  in the pipeline — a known, standing gap, not a one-off.

**Practice this implies for every new handler, not just a nice-to-have:**
before writing a handler-local regex for a type list, zone name, number,
or "you may"/"up to N" phrasing, check whether `subgrammars.py` (or an
existing sibling handler) already has it — extend the shared helper and
have your handler call it, rather than copying the pattern inline. If you
discover a phrasing brittleness like either example above, fix it in the
shared layer (`normalize.py`/`segmenter.py`/`subgrammars.py`) so every
present and future handler benefits, not with a local workaround scoped to
the one card that exposed it — a local fix is a half-fix that leaves the
same landmine for the next handler to step on.

---

# THE COVERAGE GATE: FAIL-CLOSED, ALL-OR-NOTHING

The gate turns "are all the oracle-text parts identified?" into a checkable
invariant: after segmentation, **every span of the card's text must be
claimed by exactly one handler, with zero residue** (like a lexer that must
consume its entire input).

**A card is `MODELED` only if every span — trigger wrappers, costs, keyword
abilities, and effect clauses — is claimed.** Any unclaimed span →
`UNMODELED`. No partial modeling, ever: a spell that resolves *half* of
what it says produces silently wrong game states, which is worse than one
that is honestly not implemented yet.

Three consequences:

1. **This gates the game engine, not the card cache.** An `UNMODELED` card
   still lives in the cache with oracle text, images, and mana cost — deck
   building, analysis, and display are unaffected. It simply cannot be
   cast/resolved in gameplay. The card cache stays complete; the *effect
   layer* is what's gated.
2. **Cards flip to `MODELED` with zero card-specific work.** The
   processing-list unit is the deduped *clause template*, not the card, so
   one new handler can complete the last missing clause on many cards at
   once. The gate therefore **re-runs over the `UNMODELED` set whenever
   `catalogue_version` bumps.**
3. **Coverage is the roadmap.** Two metrics fall out: `% of cache modeled`,
   and a backlog of clause templates **ranked by how many cards each would
   unlock.** That ranking *is* the build order for handlers.

---

# RUNTIME LINKING: PARSE-ON-LOAD, BIND-PER-GAME

Because the deterministic parse is cheap (regex over normalized text), the
base design **does not persist the link.** The repo catalogue is the sole
source of truth; the link is recomputed whenever a card is served, so there
is nothing to invalidate — add a handler and the next load reflects it.

Linking splits into two runtime phases by durability:

1. **Parse** — `oracle_text → AbilitySpec[]`. Runs at **load time**, right
   where
   [`LazyCardLoader.load_cards`](../../backend/mtg_analyzer/services/lazy_card_loader.py)
   returns (or lazily on first access). Pure, deterministic, memoizable.
2. **Bind** — `AbilitySpec[] → GameEffect` objects attached to a
   `GameObject`. Runs **per game instance** at game start (each effect holds
   its own `source`). **Never persisted.**

Ingest (`save_card`) is unchanged and stores only the raw card. The link is
never written into the card row.

## Optional memoization (only if parse becomes hot)

Add a memo layer keyed by `catalogue_version`, as an explicitly
**disposable** derived store — its own gitignored table, reconciled like the
card DB's schema-version check but hashing the *catalogue* files, never the
card row. This is an optimization, not a source of truth.

---

# THE PROCESSING LIST + ANALYZER MODULE

> **Decision (2026-08-27): the ingest-time LLM tier described in this
> section is out of scope and not planned.** An architecture evaluation of
> this pipeline's efficiency considered it explicitly (an offline,
> schema-constrained analyzer that proposes `AbilitySpec` rows for human
> review — the design below) and the project decided against building it,
> independent of the security-boundary argument for why it *would* have
> been safe if built. Coverage growth instead relies on shared-grammar
> factoring, family/cycle templating in the hand-authored catalogue, and
> (as a separately prototyped, higher-risk option) a shallow clause-grammar
> tier ahead of the handler regexes — see
> `docs/implementation-state/PARSER_LONG_TAIL.md`. The rest of this section
> is kept as a historical record of the original design, not a roadmap.

- **Processing list** — for `UNMODELED` cards, emit their **deduped,
  template-abstracted** unclaimed clauses (literals like numbers/names
  abstracted out) so the backlog is a few hundred unique templates, not
  tens of thousands of cards. It is *derived* (regenerable by scanning the
  volatile cache against the catalogue), so it lives in the **volatile
  store** as an **input** to the analyzer. This part is already real —
  `parser/oracle/processing_list.py` ships and ranks the backlog today.
- **Analyzer module (not built, not planned — see decision above)** — the
  original design's proposal for turning templates into new handlers
  automatically. The safe form it specified: it **proposes a catalogue row
  (data) for human review and commit** — it does **not**
  synthesize-and-execute code from card text. Its **outputs** (new handler
  rows) would have landed in the **repo**. Today this step is done by hand
  (a person, optionally LLM-assisted the same way any coding task is,
  writes and reviews the handler directly against `parser_probe.py`'s
  cache-wide feedback — see `PARSER_LONG_TAIL.md`), with no automated
  proposal step.

Inputs volatile, outputs durable — the same split as the three-tier model.
This was also exactly where the never-built **LLM tier** would have
dropped in: ingest-time / offline only, output constrained to the
`AbilitySpec` / catalogue-row schema, validated identically, low-confidence
results quarantined, never in the request hot path. That design is
preserved below for reference in case the decision is revisited.

---

# SECURITY MODEL (fail-closed by construction)

1. **No `eval` / `exec`, ever.** Card text → data only; behavior comes
   exclusively from whitelisted registry factories and the fixed catalogue
   interpreter.
2. **Validate the IR at the boundary.** Unknown `effect_type` → quarantine
   (don't raise into a live game session). **Clamp params** (cap
   damage/draw/X and any repeat count) so a malformed spec can't wedge a
   session.
3. **ReDoS resistance.** Anchored/linear regexes, a hard size cap on
   `oracle_text`, a tokenizer over catastrophic backtracking.
4. **LLM tier isolation (historical — the tier itself is out of scope, see
   the decision under "THE PROCESSING LIST + ANALYZER MODULE").** As
   designed, had it been built: structured-output only, schema-validated,
   timeout-bounded, offline. Anything the model can emit, a real card could
   too — the schema is the ceiling.
5. **Fail-closed.** Any unclaimed span → whole card `UNMODELED`; never a
   crash (protects the session), never a silent guess (protects
   correctness).
6. **Provenance.** Every spec carries `parser.version` + `source` for audit
   and cache invalidation.

---

# SCALABILITY

- **Parse once conceptually, recompute cheaply.** Deterministic front-end
  is microsecond-scale — the only tier that exists or is planned to run.
- **Stateless, no `game/` imports** → the front-end is trivially
  parallelizable and could run as a standalone service.
- **Template-abstracted backlog** keeps the analyzer's problem bounded to
  unique clause templates.
- **Coverage metrics** make the build order data-driven, not guesswork.

---

# PACKAGE LAYOUT

```
parser/oracle/            # FRONT-END — pure, no game/ imports
  normalize.py            # reminder-strip, digit-words, plural folding
  segmenter.py            # split abilities; peel trigger/cost/keyword wrappers
  catalogue/              # the repo-committed handler catalogue
    handlers.py           # declarative rows {regex, effect_type, param_mapping}
    subgrammars.py        # shared TARGET / NUMBER / DURATION matchers
    code_handlers.py      # escape hatch for irregular cards
  spec.py                 # AbilitySpec dataclasses + JSON (de)serialize + validate
  gate.py                 # full-span coverage check → MODELED / UNMODELED
  processing_list.py      # template-abstract + dedupe unclaimed clauses
  # analyzer.py            # NOT PLANNED — see the 2026-08-27 decision above

game/effect_binder.py     # BACK-END — AbilitySpec[] → GameEffect via EffectRegistry
services/card_effects.py  # (optional) disposable memo cache keyed by catalogue_version
```

---

# PHASED IMPLEMENTATION PLAN

- **Phase 0 — IR + binder + one card end-to-end.** Define `AbilitySpec`,
  write the binder over the existing `EffectRegistry`, hand-wire one card
  (e.g. Lightning Bolt) through IR → binder → `spell_effects` → resolves in
  a game test. Proves the seam with **no parsing** and a few hundred lines.
- **Phase 1 — deterministic handler table + coverage gate.** Normalize,
  segment, and the effect-family handlers for what the engine already
  supports (damage/draw/destroy/discard/gain_life/counter/search) +
  keywords. Factored sub-grammars. Coverage metric in tests.
- **Phase 2 — triggered/activated/static wiring + load-time linking.**
  Trigger-phrase → `EventType` table, cost parsing, attach to `GameObject`
  ability lists; parse-on-load in `LazyCardLoader`; optional memo cache.
- **Phase 3 — analyzer + LLM fallback. Decided against, not planned** (see
  the decision under "THE PROCESSING LIST + ANALYZER MODULE"). The
  template backlog and review pipeline it would have fed
  (`processing_list.py`) are still real and in use for hand-authoring; the
  ingest-time LLM tier itself was never built and won't be.

Phase 0 de-risks the entire design by validating the IR boundary against
the real `RulesEngine` before any NLP is written.

---

# INTEGRATION POINTS (existing code touched)

- `game/effects.py` — `EffectRegistry` is the binder's target; extend with
  new effect types as handlers need them.
- `game/rules_engine.py` — `_effects_for_spell` / the `spell_effects` hook
  is where a spell's bound effects arrive (already the designed seam).
- `models/game_object.py` — `triggered_abilities` / `replacement_effects` /
  `static_effects` / `activated_abilities` lists receive bound permanents'
  effects.
- `services/lazy_card_loader.py` — `load_cards` return is the parse-on-load
  hook; `save_card` stays raw-card-only.
- `models/events.py` — `EventType` is the vocabulary `trigger.event` maps
  to; new triggers may add constants here.
```

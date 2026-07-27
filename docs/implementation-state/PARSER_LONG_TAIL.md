# Oracle parser: the long tail — strategy & worked examples

The **examples** document of the three-way split (see
[BACKLOG.md](BACKLOG.md) for open tickets, `Done_*.md` for worklogs). Nothing
here is a ticket to close; it is the standing method for the indefinite part
of parser coverage, plus enumerated samples that calibrate how that tail
actually behaves.

Tracked in the backlog as a single standing entry, `PAR-12`.

## Where coverage stands

Measured by `scripts/coverage_report.py` (ledger-backed via
`services/coverage_db.py`), against the full ~34k-card Oracle universe:

**26.6% covered — 9,092 / 34,208 — as of 2026-07-27, PARSER_VERSION 34.**

"Covered" = parser-`MODELED` **or** hand-`AUTHORED`. Re-run the report rather
than trusting a figure quoted here, in `CLAUDE.md`, or in the Engine-Status
tab; after any change here, sync all three.

**Bump `PARSER_VERSION` (`parser/oracle/gate.py`) in the same session you add
a handler.** The ledger is keyed on content-hash **+ version**, so measuring
twice within one batch (bump, measure, add more handlers, measure again)
silently reuses the first run's rows. Either bump again or delete that
version's rows. Hand-authoring alone needs no bump — `content_hash` folds in
`ability_catalogue.is_registered`.

## How the tail gets closed

The remaining ~25k templates are, by construction, not generic. This is an
*indefinite program*, not a finite batch list, and proceeds two ways:

1. **Narrow parser extensions** for singleton shapes that still generalize a
   little — a slightly different targeting scope, a compound filter.
   Preferred: each still pays off across a small cluster.
2. **Hand-authoring** genuinely unique cards in `game/ability_catalogue.py`
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

## Lessons that keep recurring

Each was paid for once; re-reading them is cheaper than re-learning them.

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

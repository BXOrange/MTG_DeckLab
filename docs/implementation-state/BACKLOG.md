# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Put a new line in the right document:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history, no residue. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the parser tail. |
| **Singleton queue** | [singletons.md](singletons.md) | One-off cards (confirmed via `parser_probe.py blocked` to share no cluster) — a queue for `hand-author-card`, never batched into a ticket; promote a pair that shares a shape. |
| **Working memory** | [workingOn.md](workingOn.md) | Resumable state of the ticket in progress, incl. a partly done ticket's **residue**. Read first when resuming; delete the block on close. |

**Closing a ticket = deleting it here** and filing its narrative in the matching `Done_*.md`
section — no `[x]`, "shipped" note or "moved to Done" pointer. A partly done ticket keeps only its
terse open point (id, title, one clause) here; residue goes in its `workingOn.md` block. Ticket ids
are stable; reuse a retired id only for the same subject. Sequencing:
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md). Parked tickets and permanent non-goals live in
[DEFERRED.md](DEFERRED.md) (promote by moving the block back here).

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 (LLM + presentation) |
| `BUG` | Bugs — a shipped behaviour that is wrong (a wrong-but-`MODELED` claim, a silently dropped clause); not missing coverage |

---

## ENG — Game engine

-No Tickets-

## PAR — Parser

Fragment-mining tickets (PAR-208…214): measure with the `find-fragments` skill before and after
(`--ngrams`/`--ablate` for phrases); each ticket re-scans, diffs full-pool specs for zero
regressions, and executes newly claimed cards rather than trusting parse verdicts. Order: PAR-208
and PAR-210 first (re-scan after them); PAR-213 needs PAR-208 and PAR-210, PAR-214 needs
PAR-210, PAR-212's pronoun-bound forms need PAR-210; PAR-209 and PAR-211 are independent.

- **PAR-208 · Clause separators and outcome chains.** Compose clauses the segmenter now leaves
  alone: sentence follow-ups inside one paragraph (about 4,100 multi-sentence open clauses; the
  follow-up is usually where it fails), shared-subject effect lists (`target player mills 2 cards,
  draws 2 cards, and loses 2 life`), `, then` sequencing, and outcome-dependent follow-ups
  (`if you do / if you don't / if you can't / if a player does / otherwise`) bound to the preceding
  optional or conditional action. Check PAR-204 composition (`pay_cost_then`, `may_effect_then`)
  first and extend it; no second chain mechanism. Done when the multi-sentence open count drops in a
  re-scan and chained cards execute in order with correct else branches.
- **PAR-209 · Base grammar atoms.** Shared building blocks that recur inside otherwise different
  clauses, built once and reused: object filters (`target <adjective> <type>`, `that creature`, `each
  creature that player controls`), durations (`for as long as`, `until your next turn`, `until end
  of turn`), quantities (`a number of cards equal to …`, `for each …`, X and `where X is …`, `base
  power and toughness N/N`), same-name / `exiled with ~` references, and `prevent … damage`
  scopes. First step: add a slot decomposition (action, object filter, duration, quantity,
  condition) to `find-fragments`, then pick the slot values that complete the most cards in
  combination. Depends on nothing; sequence after PAR-207 and PAR-208 so their re-scan shows what
  remains.

- **PAR-210 · Shared object-phrase grammar and reference binding.** Rows carry their own object
  grammar per verb, so the same object form claims under one verb and not under the next: a probe
  of 21 verb templates × 16 object forms (`find-fragments/scripts/generalization_matrix.py`) claims
  132 of 336 cells; `that creature`, `them`, `those creatures` and `up to two target creatures` claim
  almost nowhere, `each` / `all` forms under only some verbs. About 5,700 open fragments carry a
  back-reference: 840 follow a claimable sentence (`untap it`, `you may play it this turn`, `it
  can't block this turn`, `it gains haste`), 2,030 follow a sentence that is itself open (dig /
  search / copy-spell leads: fix the lead), 2,820 are inside one sentence (`sacrifice it unless …`,
  `escapes with a counter on it`; only 41 claim once `it` is read as `~`). The engine already has the
  selectors (`previous_subject`, `previous_target`, `previous_targets`, `previous_selector`), so the
  gap is the parser side. Build one object-phrase grammar (target / each / all / up to N / pronoun
  and `that <noun>` forms) that every verb row consumes and that resolves back-references to those
  selectors, fail-closed when the antecedent is ambiguous or absent. First step, the 14 cards the
  gate's antecedent checks reject: `that player loses N life` is limited to `BECOMES_TARGET`
  (`life_loss._lose_life_that_controller`) and needs the cast / combat-damage events (Soot Imp,
  Curse of Wizardry, Kambal, Yawgmoth's Edict, Krydle of Baldur's Gate; verify the engine's
  `SPELL_CAST` event carries the casting player); `that much` has no source for counters removed as
  a cost (Geistflame Reservoir, Relic Amulet) or permanents sacrificed this turn (Sawblade
  Skinripper); Scroll of Griselbrand binds `that player` to an earlier `target opponent`; Aphelia
  nests a `whenever` inside an activated ability. Sequence after PAR-207 and PAR-208.
- **PAR-211 · Quantifier scopes.** `each` / `all` / `each other` scopes combined with the clause
  parts that depend on them stay open at a share of 0.78–0.90 against modelled text: `each player` /
  `each opponent` / `each other player` as the acting or affected set, `each creature that player /
  that planeswalker's controller / your opponents control`, `for each <thing>` repeats, `all
  <objects> that <condition>`, and the scope carried into a duration or damage clause (`until end of
  turn`, `all combat damage that would be dealt …`). Build one scope grammar (set × controller ×
  per-member repeat) that the existing target/selector resolver consumes, instead of per-phrase rows.
  Measure with `find-fragments --slots` (`obj:eachall` rows). Done when those rows drop in a re-scan
  and each-player / each-creature clauses execute per member in the real engine.
- **PAR-212 · Object-state conditions and zone-destination actions.** Two slot families that stay
  open together with a pronoun or `if`: (a) conditions on the state of an object or the game before
  the effect (`if target attacking creature token is the chosen type`, `if you control more
  creatures than each other player`, `if an <type> crewed it this turn`, `if <name>'s emerge cost
  was paid`), open share 0.83–0.93; (b) actions that name a destination zone (`put … onto the
  battlefield / on the bottom of / into your hand`, `exile … with N <counter> on it`, `exile all
  graveyards`), open share 0.81–0.96. Extend `static_conditions.py` / `effect_conditions.py` (shared
  predicate vocabulary) and the zone-destination wording of the existing move/exile primitives; do
  not add a second condition mechanism. Depends on PAR-210 for the pronoun-bound forms.

- **PAR-213 · Library and hand inspection sequences.** The lead sentence of a multi-sentence
  look / reveal / choose / dispose sequence stays open when its follow-up is not one of the whole-block
  templates `catalogue/dig.py` claims, and then every later sentence referring to it fails with it
  (about 1,580 cards have a back-reference follow-up whose lead is open; 330 are dig / reveal-top
  leads, 290 exile / cast, 120 copy, 100 search). Largest leads: `look at the top N cards of your
  library` (26 cards), `target opponent / player reveals their hand` (32), `reveal the top N cards`
  (19), upkeep / activated `look at the top card` (30), `you choose a nonland card from it` (14),
  `if you do, put ~ onto the battlefield`. Compose the sequence from steps (lead × selection ×
  disposal of the rest) that pass the inspected set along via `previous_selector`, instead of
  whole-sequence regexes; the dig families PAR-144 left open (x counts refused on purpose) stay
  fail-closed. Follow-ups to check once the lead claims: `put the rest on the bottom … in a random
  order` (52 cards), `if you search your library this way, shuffle` (51), `then that player
  shuffles` (35), `you may choose new targets for the copy` (50). Done when those sentences claim
  as part of their sequence and the sequences execute against a real library / hand.
- **PAR-214 · Missing verb-phrase rows for existing effects.** Phrases the verb × object probe
  shows no row for, although the engine has the effect (`cant_be_regenerated`, `cast_from_exile`,
  ability-loss in `physical_properties.py`; grep before assuming a primitive is missing): `<object>
  loses all abilities` (56 open cards), a stand-alone `<object> can't be regenerated` sentence
  (about 37 follow-up cards), `you may cast / play <object> this turn` as a follow-up to an exile or
  reveal (about 32), `<object> gains haste` / `untap <object>` / `<object> can't block this turn` as
  follow-ups (about 60). Each row must take the shared object phrase of PAR-210 rather than its own
  target grammar. Done when `generalization_matrix.py` shows these rows filled across the object
  forms that are valid Magic text.

## MEC — Game mechanic


## PLR — Player management


- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck. Also what actually
  closes the collision gap the PLR-4 client-token stub (`services/
  lobby.py`'s `client_token`, `Done_Backend.md` "Client-token identity
  stub") only covers halfway: that token is unsigned, client-trusted data —
  copy/clear/forge it and nothing notices — and a client that has never
  opened Profil still resolves purely by name, the original "two people
  sharing a name share a seat" collision. Fine for a LAN table, not for
  anything public.

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. ANA-1 backend contract is available (see
  [LLM integration](../Reference/LLM_INTEGRATION.md)).
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  The backend provides `created_at` and `cached`.

## BUG — Bugs


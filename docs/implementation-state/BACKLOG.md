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

Fragment-mining tickets (PAR-207…209): measure with the `find-fragments` skill before and after
(`--ngrams`/`--ablate` for phrases); each ticket re-scans, diffs full-pool specs for zero
regressions, and executes newly claimed cards rather than trusting parse verdicts.

- **PAR-207 · Trigger and activation heads.** About 1,065 open sentences fail on the head itself
  (766 distinct heads; 42 occur on three or more cards). Largest families: reflexive `when you do`;
  delayed `at the beginning of the next end step / that turn's end step / your next upkeep / the
  chosen or enchanted player's upkeep`; `when this <type> enters`; `whenever you activate …`
  (exhaust, loyalty abilities); `… this way` and threshold heads (`when you pay this cost N or more
  times`, `when the Nth <counter> is put on ~`); `whenever <attached/equipped> … attacks / is
  attacked / becomes (un)attached`. Build them as composable head grammar (trigger event × scope ×
  timing), not per-phrase rows. Done when the head-failing share in a re-scan drops and every new
  head fires in the real engine.
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

- **BUG-36 · Undo onto an open as-enters choice loses the permanent.** After `GameSession.rewind` back to an open "as ~ enters, choose …" choice (card name, creature type, colour, …), the choice is still offered and accepted but the permanent never enters: `RulesEngine._pending_enter_choice_obj/_effect/_continuation` live on the engine (a closure), not in `GameState`, so the restored state has no continuation. Repro: Meddling Mage via `GameSession`, answer the name, `rewind(1)`, answer again → battlefield empty. Fix: make the entry-choice pipeline state-owned and clone-safe like `pending_permanent_entry` (RULE 614.12, 400.7); undoing the whole cast already works.

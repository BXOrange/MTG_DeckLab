# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Replaces the former
per-half `ToDo_Backend.md` / `ToDo_Frontend.md`, which no longer exist.

Three kinds of document, kept strictly apart — put a new line in the right
one:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | Append-only. What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the indefinite parser tail. |

**Closing a ticket = deleting it from this file** and appending its narrative
to the matching `Done_*.md` section. Never leave a `[x]`, a "shipped" note,
or a "moved to Done" pointer here — this file is read in full, often, so
anything finished that stays costs every future read. If only part of a
ticket is done, keep only the part that isn't.

Ticket ids are stable; reuse a retired id only for the same subject.
Plan-level sequencing lives in
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

**Parked tickets and permanent non-goals live in [DEFERRED.md](DEFERRED.md)**,
not here — low-priority / large-and-unscheduled work, plus the "never to be
built" guardrails (Stickers, Attractions, Vanguard avatars). Keeping them out
of this file is deliberate: `BACKLOG.md` is read in full often, so it holds
only work that's actually up for scheduling. Promote a parked ticket by moving
its block back into the matching section here.

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 (LLM + presentation) |

---

## ENG — Game engine

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, coverage, worked examples, and the Commander-legal
  tail sweep (`scripts/commander_tail_report.py`'s bucket taxonomy, and
  everything `PAR-31…PAR-53` ever tracked) all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) now — not here, and not as a
  second, separate quasi-ticket the way `PAR-31…PAR-53` used to sit
  alongside this one. Parser coverage is an *indefinite standing project
  goal*, not a batch with an end date — that was already true of this
  entry, and `PAR-31…PAR-53` was never really a different kind of thing,
  just a differently-prioritized slice of the identical indefinite sweep
  (Commander-legal-first instead of raw-cache-first). Folded together
  2026-09-15 so the split matches what each half actually is, not
  historical accident. Two tracks: **basic mechanics** (generic shapes,
  cache-wide yield) — easy big wins **exhausted** as of 2026-08-28 — and
  **set-specific mechanics** (a set/precon's signature keyword, worked
  deck-first against a saved deck), now the primary track: audit a real
  deck's card list, don't re-mine `rank`. Planechase/Archenemy plane/scheme
  card *bodies* fold in here too (triggers already recognized, ~13/309
  bodies done) — not a separate ticket.

  > **Ticket-id note:** every number from `PAR-1` through `PAR-72` is
  > already a real, shipped, cross-referenced ticket, and **every one of
  > them is closed** — grep `Done_Backend.md` before reusing one (`PAR-14`,
  > for one, is RULE 603.2's once-per-turn trigger limiter, nothing to do
  > with keywords). `PAR-31…PAR-53` was this cluster's own reserved id
  > block (see [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) for what shipped
  > under it and its current status). The first free parser ticket id is
  > **`PAR-73`** (checked 2026-09-15). A genuinely new engine primitive
  > found along the way (missing behaviour, not just a parser gap) still
  > files as its own real, closeable `MEC-*` ticket below — that part of
  > the sweep stays in this file, since a primitive is schedulable work
  > with an end state, unlike the sweep itself.

## MEC — Game mechanics

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

- **VIS-4 · Chat / emotes at the table.**
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9.
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

- **ANA-1 · `POST /api/decks/{id}/analyze`.** Claude API integration, prompt
  templates, structured output parsing, caching (docs/02 UC2, docs/04 Phase
  6). `Deck.analysis_id` is reserved to link a saved deck to the result, but
  no `Analysis` model/table exists — design it alongside the endpoint rather
  than assuming the reserved field's shape is final.
- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. Blocked on [ANA-1].
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  Blocked on [ANA-1].

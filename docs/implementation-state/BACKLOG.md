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
  ticket).** Strategy, coverage, and worked examples live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Two tracks: **basic
  mechanics** (generic shapes, cache-wide yield) — easy big wins
  **exhausted** as of 2026-08-28 — and **set-specific mechanics**
  (a set/precon's signature keyword, worked deck-first against a saved
  deck), now the primary track: audit a real deck's card list, don't
  re-mine `rank`. Planechase/Archenemy plane/scheme card *bodies* fold in
  here too (triggers already recognized, ~13/309 bodies done) — not a
  separate ticket.

  > **Ticket-id note:** every number from `PAR-1` through `PAR-72` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase, and **every one of them is closed** — grep `Done_Backend.md`
  > before reusing one (`PAR-14`, for one, is RULE 603.2's once-per-turn
  > trigger limiter, nothing to do with keywords). The first free parser
  > ticket id is **`PAR-73`** (checked 2026-09-14). `PAR-31…PAR-53` names
  > the Commander-legal tail cluster below; every other id up to `PAR-72`
  > is closed narrative only, not a live pointer — don't read a stale
  > "open below" claim from an earlier revision of this note as still true
  > without checking `Done_Backend.md` first. Bucket C's three-line
  > placeholder ("file from the next free id … when their batch comes up")
  > was resolved into real tickets — `PAR-69` through `PAR-72` and
  > `MEC-86`, filed 2026-09-14 (see below); `PAR-69`/`PAR-70`/`PAR-71`/
  > `PAR-72` all closed the same day.

- **PAR-31…PAR-53 · Commander-legal tail — one PAR per recurring template
  cluster.** Seeded from `scripts/commander_tail_report.py` (read-only,
  segments every still-UNMODELED **Commander-legal** card by *cause* into
  buckets A–F; A = wrapper/segmenter re-measure, B = recurring template, C =
  set-specific mechanic, D = missing primitive → `MEC-*`, E = bespoke
  hand-authoring tail → PAR-12). **Re-run the tool and `parser_probe.py
  blocked '<regex>'` before starting a batch** — any `#` count quoted in a
  past entry here was already stale by the time it was read; the tool's own
  live output is the only trustworthy count. Close each the normal way
  (delete the line, narrate in `Done_Backend.md`, bump `PARSER_VERSION` —
  unless the batch turned out fully hand-authored, which needs none — sync
  the three coverage figures, sweep for siblings; a genuinely singleton
  card with no nearby cluster goes to `game/ability_catalogue/` instead of
  new parser grammar, per the extend-parser skill's own rule). Full method:
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md); a v298 bucket segmentation is
  in
  [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](../concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md)
  §5.3 (stale — re-run the tool rather than trusting it). Every ticket
  shall be completed end to end without leaving residue before moving to
  the next ticket.

  No open Bucket B (recurring effect-body / static template) items right
  now — PAR-67/PAR-68 (the last two) both closed 2026-09-14.

  Bucket C (set-specific mechanics, deck-first) resolved into five tickets
  2026-09-14, traced card-by-card with `commander_tail_report.py` +
  `parser_probe.py card`/`blocked` rather than taken at the report's loose
  keyword-match counts — two of the report's five raw clusters turned out to
  be residue from *already-closed* tickets (Party, Ki-counter/
  Spirit-or-Arcane) whose real remaining gap is a generic primitive, not the
  named set mechanic. PAR-69 through PAR-72 all closed 2026-09-14 — see
  `Done_Backend.md`'s "Keyword Catalogue" (PAR-69) and "Oracle-Text Parser
  Front-End" (PAR-70/PAR-71/PAR-72) entries. PAR-71's own residue — Imp's
  Mischief ("You lose life equal to that spell's mana value.") and
  Draining Whelk ("Put X +1/+1 counters on this creature, where X is that
  spell's mana value.") — print the *countered-target* referent on
  `lose_life`/`add_counters`, the one pairing that batch didn't build
  (no card needed it); stays [PAR-12] bespoke tail rather than a new
  ticket, same as PAR-69's own Rose Noble/An Unearthly Child residue.
  PAR-72's own residue — Acquisitions Expert's "target opponent reveals a
  number of cards from their hand equal to the number of creatures in your
  party. You choose one of those cards..." — needs the *hand's owner*
  (not the caster) to pick which cards get revealed, a genuinely different
  two-step interactive primitive from `RevealHandChooseDiscardEffect`'s
  "reveal the whole hand" template; also stays [PAR-12] bespoke tail.
  - **Non-goal / lowest priority, no ticket:** Attractions (RULE 717),
    Conspiracy draft-matters — moved to [DEFERRED.md](DEFERRED.md)'s
    "Permanent non-goals" section 2026-09-14; see that file for the traced
    reasoning. Banding and Horsemanship were tagged alongside these by the
    same report pass and were **not** non-goals either — both needed (and,
    2026-09-15, got) real engine primitives; see `Done_Backend.md`'s
    "Combat / Evasion Keywords" entry. Each residual card left in their own
    now-"(dead pool)" buckets after that batch (`Nature's Blessing`,
    `Tolaria`, `Urza's Avenger`, `Wall of Caltrops`, `The Girl in the
    Fireplace`) is blocked by its own separate, non-keyword-specific
    template gap (a modal "your choice of `<kw1>`, `<kw2>`, …" grant, a new
    activation-timing marker, an "or `<creature>` gains X instead"
    alternative-effect body, a board-state conditional trigger, and the
    ~60-card "create a *named* token, then a follow-up sentence grants it a
    quoted ability" family) — each traced and left as documented [PAR-12]
    bespoke-tail residue rather than promoted to a new ticket; see
    `Done_Backend.md` for the individual reasoning.

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

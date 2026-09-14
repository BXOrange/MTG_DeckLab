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

  > **Ticket-id note:** every number from `PAR-1` through `PAR-68` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase, and **every one of them is closed** — grep `Done_Backend.md`
  > before reusing one (`PAR-14`, for one, is RULE 603.2's once-per-turn
  > trigger limiter, nothing to do with keywords). The first free parser
  > ticket id is **`PAR-69`** (checked 2026-09-14). `PAR-31…PAR-53` names
  > the Commander-legal tail cluster below; every other id up to `PAR-68`
  > is closed narrative only, not a live pointer — don't read a stale
  > "open below" claim from an earlier revision of this note as still true
  > without checking `Done_Backend.md` first. Bucket C's three-line
  > placeholder ("file from the next free id … when their batch comes up")
  > is now resolved into real tickets — `PAR-69` through `PAR-72` and
  > `MEC-86`, filed 2026-09-14 (see below) — so the next free parser id
  > after this batch closes is `PAR-73`.

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
  named set mechanic:

  - **PAR-69 · Doctor's companion static keyword.** `commander_tail_report`
    tags 28 Commander-legal cards, but only 5 are solo-blocked by the
    `"doctor's companion"` keyword-grant clause itself (`Barbara Wright`,
    `Nardole, Resourceful Cyborg`, `Yasmin Khan`, `Rose Noble`, `An Unearthly
    Child`) — the other 23 also carry an unrelated bespoke ability body
    (fight triggers, ability-copying, Saga chapters, suspend interaction)
    that this clause won't unlock. Scope this ticket to the keyword clause
    only; the 23 stay [PAR-12] bespoke tail, same pattern Party/Ki already
    went through — don't let that residue block closing this one.
  - **PAR-70 · Rebel/Mercenary recruiter tutor chain (Mercadian Masques).**
    One uniform template: `"<cost>: search your library for a rebel/
    mercenary permanent card with mana value N or less, put it onto the
    battlefield, then shuffle."` 20 tagged, 17 solo-blocked. Reuses the
    existing tutor/search-onto-battlefield one-shot primitive — parser
    recognition only, no new engine work expected.
  - **PAR-71 · "that spell's `<field>`" trigger-event amount referent.**
    Traced from the report's "Ki counter / Spirit-or-Arcane" residue: the
    `"whenever you cast a spirit or arcane spell"` trigger is already
    recognized (closed), and every residue card's actual blocker is
    `"that spell's mana value"` as an amount referent on a cast-trigger.
    That phrasing spans 53 cards across the whole cache (`Aetherflux Car`,
    `Manaplasm`, `Breeches, the Blastmaker`, MV-scaled counterspell riders,
    …), 43 solo-blocked — almost none of them Kamigawa cards. Likely
    extends the already-shipped `effect_amounts` `trigger_event` kind
    (v317) to read the triggering spell's mana value rather than needing a
    new primitive. Closing this retires the "Ki-counter residue" framing;
    the Kirin cluster (`Bounteous Kirin`, `Celestial Kirin`, `Cloudhoof
    Kirin`, `Infernal Kirin`, …) is a strict subset of this, not a separate
    ticket.
  - **PAR-72 · Generalize the party count into `effect_amounts`.** Traced
    from the report's "Party" residue: `creatures_in_your_party` already
    exists as a count selector but is wired only for cost-reduction and the
    "full party" boolean condition (the ticket that shipped it). ~10-11
    cards (`Acquisitions Expert`, `Allied Assault`, `Archpriest of Iona`,
    `Ardent Electromancer`, …) are solo-blocked wanting that same count as a
    general numeric amount (P/T equal-to, mana-add-equal-to, life-loss-
    equal-to). Replaces the "Party residue" framing — the mechanic itself
    already works, this is a widening.
  - **Non-goal / lowest priority, no ticket:** Attractions (RULE 717),
    Conspiracy draft-matters — moved to [DEFERRED.md](DEFERRED.md)'s
    "Permanent non-goals" section 2026-09-14; see that file for the traced
    reasoning. (Banding and Horsemanship were tagged alongside these by the
    same report pass but are **not** non-goals — both are live on real
    Commander-legal cards with zero engine support; see `MEC-87`/`MEC-88`
    below.)

  `MEC-86` (Prepared mechanic, the report's third named item), `MEC-87`
  (Horsemanship), and `MEC-88` (Banding) all need a new engine primitive
  rather than just a parser handler, so they're filed under `## MEC` below
  instead of here.

## MEC — Game mechanics

- **MEC-86 · Prepared (the "sos" set's DFC-adjacent mechanic).** Oracle
  text: *"This creature enters prepared. (While it's prepared, you may
  cast a copy of its spell. Doing so unprepares it.)"* — a real Scryfall
  keyword (`keywords: ['Prepared']`), traced from
  `commander_tail_report.py`'s Bucket C "enters prepared" cluster (26
  tagged Commander-legal cards, 22 solo-blocked, e.g. `Adventurous Eater //
  Have a Bite`, `Blazing Firesinger // Seething Song`, `Campus Composer //
  Aqueous Aria`, `Cheerful Osteomancer // Raise Dead`). Grepping
  `backend/mtg_analyzer` for "prepare" (any case) returns zero hits
  anywhere — no state flag, no granted-permission handling exists yet,
  despite CLAUDE.md's architecture summary listing "Prepared casting"
  among already-shipped casting mechanics (that line covers only the
  layout-level DFC parsing, not this battlefield permission — fix it when
  this closes). Needs a genuine new primitive: a "prepared" state flag on
  the permanent set by its ETB, plus a granted "cast a copy of the linked
  face's spell, then clear the flag" permission — closest existing
  precedent to adapt from is the granted "cast from an unusual zone/state"
  shape in `game/top_library.py`, though this is permanent-scoped and
  flag-gated rather than zone-scoped. Ship the parser handler for `"~
  enters prepared"` in the same batch — one MEC ticket is the engine
  primitive, its oracle handler(s), and a `PARSER_VERSION` bump, together.

- **MEC-87 · Horsemanship (RULE 702.31).** A plain evasion keyword — "can't
  be blocked except by creatures with horsemanship" — structurally
  identical to Flying/Reach's block restriction, just under a different
  name; `parser/oracle/catalogue/keywords.py` already recognizes the bare
  word (row 266), but `game/combat.py`'s evasion family (`has_fear`,
  `has_intimidate`, `has_skulk`, …, `can_block`) has no Horsemanship check
  at all — confirmed by grep, zero hits for "horsemanship" anywhere outside
  the keyword catalogue. Real, live cards need it both ways: `Taoist
  Mystic` grants itself evasion ("can't be blocked by creatures with
  horsemanship" — trivially true today since nothing has it, but wrong the
  moment the keyword exists) and `Riding the Dilu Horse` grants it to
  another creature ("target creature gets +2/+2 and gains horsemanship").
  Traced from `commander_tail_report.py`'s Bucket C "Horsemanship" cluster:
  10 tagged Commander-legal cards, 8 solo-blocked (`Borrowing the East
  Wind`, `Broken Dam`, `Riding the Dilu Horse`, `Rolling Earthquake`,
  `Taoist Mystic`, …) — all either a "with/without horsemanship" creature
  filter (damage/tap effects) or a "gains horsemanship" pump-grant, no
  clause is the bare block-restriction itself (those cards are already
  MODELED via the keyword catalogue, just not functionally enforced —
  don't ship this as parser-only the way PAR-30's caveat about the
  keyword catalogue warns against). Scope: wire a `has_horsemanship`
  check into `can_block` alongside the other evasion keywords, add it to
  `display_keywords`' label table, and the parser handlers for the two
  clause shapes above, in one batch.
- **MEC-88 · Banding (RULE 702.22 / 509–510).** Far more involved than
  Horsemanship: banding creatures attack/block as a group, and whichever
  player controls a banding creature in that group chooses how combat
  damage from a blocked/blocking creature is assigned among the group,
  overriding the normal attacker-assigns-own-damage rule. `game/combat.py`
  has zero banding logic today (confirmed by grep) — this needs real
  combat-system work: recognizing a band (RULE 509.2/510.1c), and routing
  damage-assignment-order choice to the banding player's controller
  instead of the attacker's during the damage step. Traced from
  `commander_tail_report.py`'s Bucket C "Banding" cluster: 15 tagged
  Commander-legal cards, 13 solo-blocked — mostly quoted grants ("white
  legendary creatures you control have 'bands with other legendary
  creatures'" — `Cathedral of Serra`, `Mountain Stronghold`; a named-token
  variant on `Master of the Hunt`) plus a modal "creature gains banding,
  first strike, or trample" on `Nature's Blessing`. The quoted-grant shape
  itself likely reuses the existing generic quoted-ability-grant family
  (v363), but — same caveat as MEC-87 — don't ship the grant recognition
  without the damage-assignment behavior it's supposed to produce; bundle
  primitive + parser handlers in one batch.

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

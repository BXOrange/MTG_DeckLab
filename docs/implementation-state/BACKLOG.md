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

  > **Ticket-id note:** every number from `PAR-1` through `PAR-30` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords; `PAR-30` was `PAR-29`'s parser trail, closed PARSER_VERSION
  > 216 — all 24 RULE 701 keyword actions have recognition + an engine
  > primitive, and its last residue moved to `MEC-52`, closed). The first free
  > parser ticket id is **`PAR-69`** (checked 2026-09-14 — `PAR-47`/`PAR-51`
  > closed an earlier pass this session, `PAR-65`/`PAR-66` filed from their
  > residue then closed *this* pass along with `PAR-53`/`PAR-56`, and
  > `PAR-67`/`PAR-68` filed from their own residue below): `PAR-31…PAR-53` are
  > the Commander-legal tail clusters below, `PAR-54`/`PAR-55`/`PAR-57`/`PAR-60`
  > `PAR-58`/`PAR-59`/`PAR-64` are open below, and `PAR-61` is the
  > grammar-restructure umbrella above.

- **PAR-31…PAR-53 · Commander-legal tail — one PAR per recurring template
  cluster.** Seeded from `scripts/commander_tail_report.py` (read-only,
  segments every still-UNMODELED **Commander-legal** card by *cause* into
  buckets A–F; A = wrapper/segmenter re-measure, B = recurring template, C =
  set-specific mechanic, D = missing primitive → `MEC-*`, E = bespoke
  hand-authoring tail → PAR-12). The `#` below is the tool's
  Commander-legal SOLO upper bound at the run cited — **re-run the tool and
  `parser_probe.py blocked '<regex>'` before starting a batch**, the real
  SOLO count is always lower. Close each the normal way (delete the line,
  narrate in `Done_Backend.md`, bump `PARSER_VERSION`, sync the three
  coverage figures, sweep for siblings). Full method:
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Counts below are from a
  PARSER_VERSION 186 run (2026-09-01) and are stale; a fresh v298 segmentation
  is in
  [13_ORACLE_PARSER_GRAMMAR_REVIEW.md](../concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md)
  §5.3. Every ticket shall be completed end to end without leaving residue
  before moving to the next ticket.

  Bucket B (recurring effect-body / static templates, `extend-parser` loop):

  - **PAR-67 · Counter-removal follow-ups beyond the plain accumulator.**
    `GameContext.counters_removed_this_way` + `RemoveCountersEffect.
    self_only`/`kind` (PAR-66, closed) already closed Coalition Relic/
    Ventifact Bottle outright; three more cards each need a *further*,
    distinct shape on top of that same primitive: **Garnet, Princess of
    Alexandria** ("remove a lore counter from **each of any number of**
    Sagas you control" — a multi-object removal across a player's own
    *choice* of permanents, not one target/self source, plus `"lore"`
    joining `_NAMED_COUNTER_KINDS`); **Lily Bowen, Raging Grandma** ("remove
    **all but one** +1/+1 counter" — a partial-removal count, not
    `RemoveCountersEffect`'s existing all-or-chosen-amount shapes); **Sage
    of Hours** ("for each **5** counters removed this way, take an extra
    turn" — a division-scaled repeat-action, not a plain 1:1 amount read).
  - **PAR-68 · Teamwork-adjacent one-offs beyond the rider condition.**
    PAR-56 (closed) already routes "if this spell was cast using teamwork"
    riders to a `teamwork_paid` condition, both the modal override and the
    leading/trailing additive shapes. What's left on real cards is each its
    own different template, not more "teamwork" grammar: a
    damage/exile/choose **magnitude override** family parallel to the
    existing kicked/bargained "instead" overrides (Helicarrier Strike,
    Cruel Alliance, Too Evil to Stay Dead, Earth's Mightiest Heroes); a
    trailing "also `<effect>` if teamwork" additive that also needs a "that
    creature" previous-target pronoun `add_counters` doesn't resolve yet
    (Beast Mode); the `Teamwork — <ability>` ability-word keyword line; two
    new trigger conditions ("whenever `<name>` becomes tapped to pay a
    teamwork cost", "whenever you cast a spell using teamwork"); and "you
    may cast this spell as though it had flash if it's cast using teamwork"
    (a cast-permission condition). HULK SMASH!/Atlantis Attacks/Murdock's
    Crusade (PAR-56's old seed cards) are each blocked by unrelated,
    generic gaps instead (a "target player creates a token" recipient, a
    `<Name> — <effect>` flavor-label-prefixed mode body, "destroy target
    noncreature artifact") — real but nothing to do with Teamwork.

  Bucket C (set-specific mechanics, deck-first):

  - Doctor's companion (Doctor Who) (#28), Rebel/Mercenary recruiter
    tutor chains (Mercadian Masques) (#21), `enters prepared` (#23) —
    file from the next free id (see the ticket-id note above) when their
    batch comes up; not enumerated further here to keep the list to the
    first wave.
  - **Non-goal / lowest priority, no ticket:** Attractions (RULE 717,
    #19 — permanent non-goal), Conspiracy draft-matters (#13), Banding
    (#13), Horsemanship (#8) — dead pools / non-goals, documented, kept
    out of the denominator with the sticker cards.

## MEC — Game mechanics

> No open tickets.
>
> New MEC tickets come from `scripts/commander_tail_report.py`'s bucket D
> (~132 Commander-legal cards; its signature labels name the *missing
> primitive*). Not filed, on purpose: the Attractions family (RULE 701.45
> Assemble, 701.51 Open an Attraction, 701.52 Roll to Visit Your Attractions)
> is a permanent non-goal in `DEFERRED.md`.

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

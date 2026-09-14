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
  > without checking `Done_Backend.md` first.

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

  Bucket C (set-specific mechanics, deck-first):

  - Doctor's companion (Doctor Who), Rebel/Mercenary recruiter tutor
    chains (Mercadian Masques), `enters prepared` — file from the next
    free id (see the ticket-id note above) when their batch comes up; not
    sized further here since the counts above are already known-stale.
  - **Non-goal / lowest priority, no ticket:** Attractions (RULE 717 —
    permanent non-goal), Conspiracy draft-matters, Banding, Horsemanship —
    dead pools / non-goals, documented, kept out of the denominator with
    the sticker cards.

## MEC — Game mechanics

- **MEC-85 · Cast-time-conditional target legality/selection count
  ("instead" overrides beyond a flat magnitude).** RULE 702.194b's
  Teamwork "instead" clauses come in two shapes: PAR-68 (closed) built
  `DealDamageEffect.amount_if_teamwork` for the flat-magnitude one
  (Helicarrier Strike — same target either way, mirrors the existing
  `amount_if_kicked`/`amount_if_bargained` family). Three more cards need
  the *other* shape, which has no primitive yet: **Cruel Alliance**
  ("exile target creature with mana value 3 or less. If this spell was
  cast using teamwork, instead exile target creature…" — the mana-value
  cap on the RULE 115 target itself is conditional, not just the effect);
  **Too Evil to Stay Dead** (same shape, a graveyard target's mana-value
  cap); **Earth's Mightiest Heroes** ("you may put a creature card from
  among them onto the battlefield. If this spell was cast using teamwork,
  put **any number** of creature cards… instead" — a selection-count
  override, "up to one" vs "any number", not a magnitude). `TargetSpec`
  carries no condition of its own today (checked — no such field exists),
  so a target-gathering pass can't yet ask "which filter applies" against
  a cast-time flag like `teamwork_paid`; RULE 601.2b/c already make this
  answerable in principle (additional costs, including Teamwork, are
  chosen and paid before targets are chosen), so the fix is a genuine new
  targeting primitive, not a resolve-time trick like `amount_if_teamwork`.
  Not the same gap as Colossal Growth's own excluded scope
  (`Done_Backend.md`'s MEC-82 entry — a magnitude override that *also*
  grants a keyword, no target-legality question at all); don't conflate
  the two when picking this up.

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

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

Fragment-axis tickets (PAR-220…224), from the v792 scan (9,179 open Commander cards, 13,440 open
sentences; the best exact template unlocks 5 cards, so each ticket is a shared grammar axis over
the PAR-210 object phrase, not template rows). Counts are `touched` / `only` (open cards with the
axis / cards whose every open sentence has it; an overlapping upper bound). Each ticket re-scans
with `find-fragments` before and after, diffs full-pool specs for zero losses and executes newly
claimed cards.

- **PAR-220 · Linked exile and cast windows.** `cards exiled with ~` (RULE 607) as a reference and
  count, `you may cast / play <exiled reference> [this turn / for as long as …]` and `without paying
  its mana cost` follow-ups over exile. 184+338 / 56+71.
- **PAR-221 · Control change and counter movement.** `gain control of <object> [for as long as …]`,
  `exchange control of <object> and <object>`, `any number of target creatures` (counted steal),
  `move / remove <quantity> <counter> counters from <object> [onto <object>]`. 140+125 / 65+66.
- **PAR-223 · Condition-bound and next-turn durations.** `for as long as <condition>`, `until your
  next upkeep / end step`, `during your next turn`, `until the end of your next turn`; `your_next_turn`
  exists, the others need engine windows (included). 138+105 / 57+40.
- **PAR-224 · Small rows for existing effects.** `target player takes an extra turn after this one`
  (only `you take` is claimed; Time Warp), `you skip your next turn`, `activate no more than twice each
  turn`, `put <object> on top / bottom of its owner's library` over the shared object phrase.
  29+43+256 / 21+22+65.

## MEC — Game mechanic

- **MEC-135 · Play windows from graveyard and library.** `Mill a card. You may play that card this
  turn` (Ark of Hunger, Tablet of Discovery) and reveal-then-cast follow-ups: `_has_temp_play_permission`
  honours only exile, so the permission is recorded but never offered (verified in PAR-214). Engine
  window plus parser rows. 15 / 3, more once PAR-220 claims the leads.

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

-No Tickets-


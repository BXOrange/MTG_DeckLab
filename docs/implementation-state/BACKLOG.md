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

- **PAR-202 · End-of-combat trigger head.** `at end of combat` (with intervening-if): 14 open, 5 with other parsed effects (Clockwork cycle, Daredevil Dragster, Dread Wight, Greater Werewolf, Heat Stroke, Kjeldoran Frostbeast, …).
- **PAR-203 · Named choices on resolution.** `choose a creature type` (23 open, 2 sole-blocker), `choose a color` (18), `choose a card name` (17); measure which already-existing choice primitive each lacks.
- **PAR-204 · Optional-payment "if you do" chains.** Compose `you may pay <cost>` and `if you do` / `if you don't` by antecedent type, including targeted counter placement before animation (Cyclone Sire, Noyan Dar, Wall of Resurgence); preserve announced targets and verify outcome gating through choices and clone.

## MEC — Game mechanic

-No Tickets-

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

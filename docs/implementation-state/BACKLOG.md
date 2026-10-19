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


## PAR — Parser


- **PAR-12 · The indefinite long tail (methodology pointer, not closeable).** Strategy, coverage,
  worked examples and the Commander-legal tail taxonomy (`scripts/commander_tail_report.py`) live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Two tracks: **basic mechanics** (generic shapes,
  cache-wide yield — re-run `rank` before trusting "exhausted"; Bucket B still finds clusters) and
  **set-specific mechanics** (a set/precon's signature keyword, worked deck-first). Planechase/
  Archenemy card bodies fold in here (~13/309 done).

  > **Ids:** `PAR-1`…`PAR-159` are taken — grep `Done_Backend.md` before reusing one. First free:
  > **`PAR-168`**; next free `MEC`: **`MEC-128`**; next free `ENG`: **`ENG-54`**; next free `VIS`: **`VIS-16`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.



- **PAR-167 · Casting-window grammar compositions.** Compose origin zone, card/spell filter, normal/free cost, resolution-local versus standing permission, expiry and post-cast exile using existing permission primitives; size each shape across the full cache. Calibrated scope: `PARSER_LONG_TAIL.md`, “Face-audit follow-ups”; independent of PAR-157.


## MEC — Game mechanic

- **MEC-125 · Cross-game delayed returns.** Model explicit paper-card instructions that carry exiled cards into a later game: persist captured cards and participants, select the qualifying next game and schedule the return by that player's turn index. Size the printed family first (Time Machine); reuse ordinary return/entry effects within the destination game. Current GameState/delayed triggers are game-local; no cross-game return primitive was found. Independent of PAR-157.

- **MEC-126 · Target-seeded shared-characteristic groups.** "Target X and each other Y that shares a color with it": announce one target, then apply the body to it and every other object sharing a color with it at resolution; needs a target-seeded group (`group_selector_objects` never sees `previous_targets`) and a shares-color-with-reference predicate. ~10 cards (Cleansing Beam, Wojek Embermage/Apothecary/Siren, Brightflame, Rally the Righteous, Surge of Zeal, Incite Hysteria, Leave No Trace, Bathe in Light); the predicate alone also serves "shares a creature type with it" filters (Heirloom Blade, Tajuru Paragon, Titan of Littjara). Includes the parser rows.

- **MEC-127 · Keep-N-then-sacrifice edicts.** "Each player chooses N <permanents> they control, then sacrifices/destroys the rest": add a keep-count to `ChoosePlayerObjectsEffect` (today only per-type `keep_types`), APNAP choices, simultaneous removal. ~8 cards (Razia's Purification, Divine Reckoning, Covetous Elegy, Single Combat, Fall of the First Civilization, Urza's Sylex, Planar Overlay, Consuming Tide). Includes the parser rows.




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

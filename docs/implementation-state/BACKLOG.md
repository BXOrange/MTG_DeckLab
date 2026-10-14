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
  > **`PAR-166`**; next free `MEC`: **`MEC-119`**; next free `ENG`: **`ENG-54`**; next free `VIS`: **`VIS-16`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.

- **PAR-132 · Dependent target/body follow-up batch.** Distinct effect-body, trigger-head and
  duration clusters exposed by PAR-130; calibrated clusters live in `PARSER_LONG_TAIL.md`.
> PAR-99…105 counts confirmed at PV 413 (2026-09-16, vs the 56 saved decks in `deck_coverage.py`),
> re-verified at PV 447 (2026-09-21). Re-run `parser_probe.py blocked` before starting.

- **PAR-146 · `commander_tail_report.py` taxonomy re-validation.** Measured at PARSER_VERSION 584
  (`PARSER_LONG_TAIL.md`, "Commander tail re-validation"): the `roll_die` row ("no dice subsystem at all",
  43 cards) and the `tapped and attacking` row (59) name primitives that exist (`RollDieEffect`,
  `create_token` `attacking`/`enter_attacking`); the Banding/Horsemanship rows describe shipped MEC-87/88;
  the other Bucket D rows (damage-source tracker 9, exchange control 7, Villainous Choice 6, collect
  evidence/forage/behold 5, suspect 3, incubate 2, clash 1, meld 1, triple 1, waterbend 1) are unchecked —
  exchange control and meld look stale (`Done_Backend.md` Gilded Drake swap; CLAUDE.md lists meld as done).
  Scope: check each remaining row with `parser_probe.py card`/`blocked`, fix or drop the stale ones, list
  Stickers in Bucket F by type line, and split Bucket E (96% of the tail) by the trigger-
  body / modifier axes `composition` reports instead of one rest bucket. Decision open: whether the report
  should print each row's check status.
- **PAR-152 · "Put/return … tapped and attacking" placements.** 16 SOLO cards whose placement clause (`put_onto_battlefield_attacking`,
  RULE 508.4) lacks its surroundings: a *placed* creature's defender choice (`_offer_attack_defenders`) with a reflexive fight (Hans
  Eriksson), a borrowed creature returned at the end step (Zara), a conditional keyword grant (Doors of Durin), exile-then-reveal
  (Fireflux Squad), a delayed return at the next declare-attackers step (Meandering/Meandered Towershell, Noctis, The Neutrinos), a
  granted trigger on the returned card (Olivia, Thunderkin Awakener), plus Jocasta, Nemesis Phoenix, Paladin Elizabeth Taggerdy, Strefan,
  Ultra Magnus, The Sprinkler of Stardust, Chorale of the Void, Zareth San.
- **PAR-149 · Bucket B candidates to validate before any handler.** Report counts at PARSER_VERSION 584, not yet
  checked with `blocked`/`card`: "cast this spell only during combat / before blockers / the declare blockers
  step" (15, three phrasings), "when enchanted creature/land dies, return that card …" (6 + 6), emblem with a
  quoted ability (48 cards, only 5 SOLO — Dack Fayden, Liliana the Last Hope, Tezzeret Artifice Master,
  A-Saheeli, The Capitoline Triad; the rest are blocked by other planeswalker abilities). Decision open: which
  of these earn a handler; the emblem case is weak on SOLO yield.
- **PAR-155 · Broader mana-ability counter riders.** Mana abilities that carry a counter rider beyond the shapes already modeled; size the real cards with `parser_probe.py rank`/`blocked` first (PLAY-ALL).

- **PAR-156 · Counter or pump, then fight.** "Put a +1/+1 counter on / pump target creature, then it fights …" sequences not yet claimed; size against the cache first, and check whether the existing `fight` previous-target rows already cover the second half (PLAY-ALL).

- **PAR-157 · Flicker with riders.** Exile-and-return clauses with an attached rider (counters, tapped, a delayed follow-up, …) beyond the plain and delayed-return blink forms already modeled; size first (PLAY-ALL).

- **PAR-158 · Multi-event attack/block/target trigger heads.** Trigger heads naming more than one event ("whenever ~ attacks, blocks, or becomes the target of …") that the segmenter does not yet split; size first (PLAY-ALL).

- **PAR-159 · Equipped-creature X pump.** "Equipped creature gets +X/+X …" statics and pumps whose X is measured off the board or the equipment; size first (PLAY-ALL).

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

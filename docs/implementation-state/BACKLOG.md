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

Fragment-mining tickets (PAR-212…214): measure with the `find-fragments` skill before and after
(`--ngrams`/`--ablate` for phrases); each ticket re-scans, diffs full-pool specs for zero
regressions, and executes newly claimed cards rather than trusting parse verdicts.
Shared base grammar, reference binding and quantifier scopes are available; the remaining tickets are unblocked.

- **PAR-212 · Object-state conditions and zone-destination actions.** Two slot families that stay
  open together with a pronoun or `if`: (a) conditions on the state of an object or the game before
  the effect (`if target attacking creature token is the chosen type`, `if you control more
  creatures than each other player`, `if an <type> crewed it this turn`, `if <name>'s emerge cost
  was paid`), open share 0.83–0.93; (b) actions that name a destination zone (`put … onto the
  battlefield / on the bottom of / into your hand`, `exile … with N <counter> on it`, `exile all
  graveyards`), open share 0.81–0.96. Extend `static_conditions.py` / `effect_conditions.py` (shared
  predicate vocabulary) and the zone-destination wording of the existing move/exile primitives; do
  not add a second condition mechanism. Depends on PAR-210 for the pronoun-bound forms.

- **PAR-213 · Library and hand inspection sequences.** The lead sentence of a multi-sentence
  look / reveal / choose / dispose sequence stays open when its follow-up is not one of the whole-block
  templates `catalogue/dig.py` claims, and then every later sentence referring to it fails with it
  (about 1,580 cards have a back-reference follow-up whose lead is open; 330 are dig / reveal-top
  leads, 290 exile / cast, 120 copy, 100 search). Largest leads: `look at the top N cards of your
  library` (26 cards), `target opponent / player reveals their hand` (32), `reveal the top N cards`
  (19), upkeep / activated `look at the top card` (30), `you choose a nonland card from it` (14),
  `if you do, put ~ onto the battlefield`. Compose the sequence from steps (lead × selection ×
  disposal of the rest) that pass the inspected set along via `previous_selector`, including
  per-player revealed-card pools (the parley family) and their per-revealed-card payoffs, instead of
  whole-sequence regexes; the dig families PAR-144 left open (x counts refused on purpose) stay
  fail-closed. Follow-ups to check once the lead claims: `put the rest on the bottom … in a random
  order` (52 cards), `if you search your library this way, shuffle` (51), `then that player
  shuffles` (32; remaining inspection leads and references), `you may choose new targets for the copy`
  (50). Done when those sentences claim as part of their sequence and the sequences execute
  against a real library / hand.
- **PAR-214 · Missing verb-phrase rows for existing effects.** Phrases the verb × object probe
  shows no row for, although the engine has the effect (`cant_be_regenerated`, `cast_from_exile`,
  ability-loss in `physical_properties.py`; grep before assuming a primitive is missing): `<object>
  loses all abilities` (56 open cards), a stand-alone `<object> can't be regenerated` sentence
  (about 37 follow-up cards), `you may cast / play <object> this turn` as a follow-up to an exile or
  reveal (about 32), `<object> gains haste` / `untap <object>` / `<object> can't block this turn` as
  follow-ups (about 60). Each row must take the shared object phrase of PAR-210 rather than its own
  target grammar. Done when `generalization_matrix.py` shows these rows filled across the object
  forms that are valid Magic text.

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


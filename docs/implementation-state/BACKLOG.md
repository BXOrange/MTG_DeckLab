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

No open tickets.

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not closeable).** Strategy, coverage,
  worked examples and the Commander-legal tail taxonomy (`scripts/commander_tail_report.py`) live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Two tracks: **basic mechanics** (generic shapes,
  cache-wide yield — re-run `rank` before trusting "exhausted"; Bucket B still finds clusters) and
  **set-specific mechanics** (a set/precon's signature keyword, worked deck-first). Planechase/
  Archenemy card bodies fold in here (~13/309 done).

  > **Ids:** `PAR-1`…`PAR-144` are taken — grep `Done_Backend.md` before reusing one. First free:
  > **`PAR-145`**; next free `MEC`: **`MEC-109`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.

- **PAR-118 · "Exile a card from your hand with N time counters on it, it gains suspend."** Alaundo
  the Seer, The Eleventh Doctor, The Wedding of River Song (3 SOLO). Suspend is engine-complete
  (`GameObject.granted_suspend`, `remove_suspend_time_counter`, `SuspendUpkeepEffect`); missing is the
  optional hand-to-exile pick stamping `time` counters = mana value + the suspend grant, Wedding's
  "target opponent does the same", and Alaundo's granted `LAST_TIME_COUNTER_REMOVED` trigger + per-owner
  "remove a time counter from each other card" sweep.
- **PAR-132 · Dependent target/body follow-up batch.** Distinct effect-body, trigger-head and
  duration clusters exposed by PAR-130; calibrated clusters live in `PARSER_LONG_TAIL.md`.
- **PAR-133 · Powerstone tokens.** "create a [tapped] Powerstone token" — a `data/tokens.json` entry
  with its RULE 605.3a-restricted mana ability, then `_NAMED_TOKEN_WORDS` (25 solo cards).
- **PAR-100 · "At the beginning of each player's draw step, that player draws an additional card".**
  "That player" binds to the player whose step it is; 10 SOLO + Mornsong Aria (Academy Loremaster,
  Anvil of Bogardan, Dictate of Kruphix, Font of Mythos, Howling Mine, Kami of the Crescent Moon,
  Nekusar, Rites of Flourishing, Spiteful Visions, Teferi's Puzzle Box).

> PAR-99…105 counts confirmed at PV 413 (2026-09-16, vs the 56 saved decks in `deck_coverage.py`),
> re-verified at PV 447 (2026-09-21). Re-run `parser_probe.py blocked` before starting.

- **PAR-107 · Small residue batch — graveyard/library/exile.** Adventure/Blitz casts from the graveyard and the
  single-card graveyard/library shapes left over.
- **PAR-108 · Small residue batch — miscellaneous shapes.** Single-card copy/counter/look-at-hand shapes and the
  remaining "the sacrificed creature's …" sub-shapes.
- **PAR-109 · Residue of the static/activated-ability batch.** Brad Boimler's until-EOT counter replacement;
  Worldknit's card-pool condition; "can't be regenerated" leftovers (Bone Shaman, Lim-Dûl's Cohort); Desolation of
  Smaug's "spend only to cast Dragon spells"; Luxior's per-counter bonus; Atalya's modal `{X}, {T}` body.
- **PAR-110 · Small residue batch — board wipes & mass effects.** Mass-damage riders, mass-tap, "destroy/exile all"
  + rider tails, total-power edicts, Living Death.
- **PAR-113 · Small residue batch — combat triggers.** "Whenever a player attacks" head and kept mana with a
  restriction or a non-trivial head.
- **PAR-114 · Small residue batch — cost reduction & alternative costs.** Either/or additional costs with no mana
  half, activation-cost and flashback-cost "where X is …" discounts, "during turns other than yours" on P/T.

> PAR-107…114 counts come from a one-pass `parse_oracle` + `abstract_clause` scan (PV 413, 2026-09-16,
> vs the 56 saved decks); 107…113 re-measured at PV 447. They were not individually re-diagnosed —
> run `parser_probe.py card` first, since intervening "if" clauses and self- vs target-referents change
> the handler shape. Traps: a `<name>` in "`X` has `<name>`" is a wrapper hiding a quoted inner ability
> (decompose before counting); loyalty costs print a Unicode minus (−).

- **PAR-126 · "A spell or ability an opponent controls causes you to discard `<X>`" — self-subject
  trigger family.** MEC-101 built the primitive (`DISCARD_CARD.cause_controller_id`,
  `requires_opponent_caused_discard`, `triggers_mixin._collect_discarded_triggers`) and hand-authored
  Pure Intentions. 12 SOLO cards remain (`blocked "causes you to discard"`), pure parser work: **(a)** a
  bare self-subject passive "~ is discarded" has no recognition (`_TRIGGER_VERBS` has no passive row,
  the self noun list has no "card"); **(b)** the "a spell or ability an opponent controls causes you to
  discard `<referent>`" wrapper (subject is the causing spell) needs its own dispatch row emitting
  `{"event": "DISCARD_CARD", "condition": {"subject": "self"|"you"}, "requires_opponent_caused_discard":
  True}` (precedent `_DAMAGE_TRIGGER_RE`); **(c)** Pure Intentions' `create_turn_trigger` (RULE 603.7a)
  needs generalizing to a parser row. Library of Leng / Nephalia Academy ("an effect causes you to
  discard") are a broader, non-opponent-scoped condition — not this cluster.

## MEC — Game mechanic

_No open tickets._

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

## BUG — Bugs

- **BUG-1 · An "Equip …" line is claimed as a keyword line and its text silently dropped.** The
  segmenter reads any line starting with "Equip" as a keyword line (`keyword_line=True`), so "Equip
  abilities you activate [that target X] cost {N} less to activate." and "Equip {N}. This ability costs
  … less to activate …" emit no spec: Bureau Headmaster, Bladehold War-Whip, Cloud Planet's Champion,
  Dwarven Mauler, Helitrooper, Plate Armor / A-Plate Armor and Warrior's Blades are `MODELED` without
  their equip-cost discount. Fix: fail the line closed unless it is a bare equip cost, then give the
  discount its own row (activation costs have no `targets` yet — see Kopala/Strong Back).
- **BUG-2 · "target player draws N cards and loses N life" in a triggered ability costs its controller the life.**
  The `lose_life` clause carries no player (`previous_subject` unset) and a trigger passes its targets only to the
  effect that declared one, so it falls back to the controller; as a spell the shared target list hides it. Wrong
  but `MODELED`: Fell Stinger, Vault Plunderer, Bloodgift Demon, Unscrupulous Contractor (and any other
  subjectless "and loses/gains …" after a targeted-player clause in a trigger).

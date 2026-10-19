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
  > **`PAR-176`**; next free `MEC`: **`MEC-128`**; next free `ENG`: **`ENG-54`**; next free `VIS`: **`VIS-16`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.

- **PAR-169 · Handler-table shadowing.** Row order in `catalogue/handlers.py` `HANDLERS` decides the
  IR, contrary to its "order matters only for reporting" comment: 39 row pairs claim the same clause
  with *different* specs (949 cached clauses), mostly legacy rows that shadow the generalized grammars
  (`add_counters_selector`/`add_pt_counter_group`, `destroy_all`·`exile_all`/`mass_group`,
  `damage_selector`·`damage_each_creature_keyword`/`damage_group`, `exile_top_play`/`exile_cast_window`,
  `tap_selector`/`tap_all_group`). Add a full-cache guard (no two eligible rows claim one clause with
  different IR, explicit allowlist), retire the shadowed row per family after a spec-fingerprint diff,
  fix the comment, and delete or justify the 39 rows that match no cached card.
- **PAR-170 · Dead Alchemy parser paths.** `support_policy` returns Unsupported for
  perpetually/specialize/conjure/seek/spellbook before parsing (PAR-168), yet the parser still carries
  them: the literal `choose_perpetual_blitz` clause and the `_perpetual_pump_specs` fallback (tried on
  every unclaimed clause) in `handlers.py`, `conjure_duplicate_into_hand`, the Specialize branches in
  `segmenter.py`/`keywords.py`. Remove them and their tests; check whether the engine-side consumers
  (`choose_perpetual_blitz`, `GameObject.perpetual_*`) are still reachable from any non-Alchemy card.
- **PAR-171 · Move the PARSER_VERSION changelog out of `gate.py`.** ~3,800 of its ~5,800 lines are
  the per-version comment log, with live code (`_ATTACH_KEYWORDS`) interleaved. Move it to its own
  version-history file (keep `PARSER_VERSION` + lock in `gate.py`), and refresh the stale
  `catalogue/__init__.py` docstring.
- **PAR-172 · Break the segmenter ⇄ handlers ⇄ static_handlers cycle; split the monoliths.** ~45
  function-scoped imports and 22 cross-module private-name imports (`_peel_optional`, `_TRIGGER_RE`,
  `_base_verb`, `_quoted_ability_grant_effects`, …) paper over the cycle. Extract the shared clause
  primitives into a leaf module; split `handlers.py` (22.9k lines) by effect family into modules that
  each export their rows, assembling `HANDLERS` in a fixed order; turn `_segment_line_unsplit`
  (2.1k lines, 74 branches) and `static_effect_specs` (1.5k lines) into ordered matcher tables like
  `HANDLERS`. Prove each step with a full-cache spec fingerprint. After PAR-169/170.
- **PAR-173 · One clause-reading context.** Replace the five threaded subject flags (`self_subject`,
  `previous_subject`, `group_subject`, `previous_selector`, `attached_subject`) and the
  `_GROUP_CLAUSE` ContextVar with one immutable reading object passed through `match_clause`,
  `parse_effect_body` and the builders that re-enter them. Natural base for PAR-175's referents.
- **PAR-174 · Mechanic flags on `AbilitySpec`.** `rad_counters_on_combat_damage`,
  `rad_counters_on_attacked`, `mill_return_from_graveyard`, `enter_or_graveyard_discard_land`,
  `impulsive_draw_on_combat_damage` and `counter_death_return` are top-level IR fields, each with its
  own validator, binder branch and `validate()` exemption. Express each as an ordinary
  triggered/replacement spec over registered effects and retire the field.
- **PAR-175 · Clause linkage across a sequence (14_ S4 + "axis 4").** `parse_effect_body` sequences
  any number of sentences/connectors, but (a) one unclaimed part discards the whole body, and (b)
  the only cross-clause state is a one-step "previous clause chose a creature" flag, so a later
  clause cannot name what an earlier one produced; multi-sentence rows (`_MAX_SENTENCE_WINDOW`)
  memorize such combinations instead. Build a referent environment (clause-produced groups/objects
  consumed by "those cards", "they", "for each of those …", "the permanent for which they were
  chosen") and residue-aware sequencing per [14_PARSER_GRAMMAR_DESIGN.md](../concepts/14_PARSER_GRAMMAR_DESIGN.md)
  S4. Reference card: Dack Fayden, Helping Hand (UNMODELED today). Size the referent families
  with `parser_probe.py` before building.





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

- **BUG-11 · Parse-cache key omits fields the parser reads.** `gate._parse_cache_key` is a hand-kept
  field list without `vehicle_power`/`vehicle_toughness` (Station `type_change` P/T) and `layout`
  (Room split), so two cards differing only there share one cached `ParseResult` (repro: Atmospheric
  Greenhouse with `vehicle_power` 5 vs. 10 both parse to power 5). Add the fields and a guard test
  that every card attribute the front-end reads is part of the key.

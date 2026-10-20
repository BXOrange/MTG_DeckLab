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
  > **`PAR-177`**; next free `MEC`: **`MEC-128`**; next free `ENG`: **`ENG-54`**; next free `VIS`: **`VIS-16`**; next free `BUG`: **`BUG-35`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.

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

- **BUG-13 · P1 · Separate actual colors from Commander color identity (RULE 202.2/903.4).**
  `models/game/game_object.py:colors` treats a Forest with green identity as a green permanent.
  Preserve face colors/color indicators separately and derive effective colors through layer 5;
  cover colored activated costs, devoid, multiple faces and downstream targeting/protection/counts.

- **BUG-14 · P1 · Apply the complete SBA set simultaneously (RULE 704.3).**
  `game/rules/sba_mixin.py` removes one object before recomputing the next sweep: zero-toughness
  Elesh Norn leaves first and saves an opposing 2/2 that was also at zero toughness. Freeze all
  applicable actions and required choices from one derived state, apply them together, then repeat.

- **BUG-15 · P1 · Order continuous effects by dependency (RULE 613.8).**
  `game/continuous.py:_in_layer` uses timestamps alone; Urborg entering after Blood Moon incorrectly
  grants Swamp. Reevaluate dependencies, including effect existence, within each layer. Correct
  `tests/test_land_type_grant_interactions.py` to require Blood Moon to suppress Urborg in either
  entry order.

- **BUG-18 · P1 · Use current battlefield types for targets, costs and selectors (RULE 613.1d).**
  `game/targeting.py` artifact/enchantment frames and `game/continuous.py:_has_card_type` read
  printed card flags. A creature made an artifact cannot be selected as an artifact. Share derived
  type checks across battlefield consumers, covering additions and removals while retaining the
  appropriate card-characteristic checks in other zones.

- **BUG-19 · P1 · Mask every illegal resolution target (RULE 608.2b/400.7).**
  `game/rules/casting_mixin.py:_mask_restricted_targets` retains failed targets that left the
  battlefield. With one legal player target remaining, a two-target damage ability still marks
  damage on its other, exiled target. Blank failed zone/visit slots centrally while preserving
  target groups, partial resolution and allocated damage.

- **BUG-20 · P1 · Give first-strike damage its own priority window (RULE 510.3–4).**
  `game/engine/turn_loop_mixin.py:_step_combat_damage` performs both damage steps synchronously;
  an unblocked 2-power double striker deals four damage before interactive priority returns.
  Schedule separate steps with SBAs, trigger placement and APNAP priority between them; preserve
  the step state through choices and undo.

- **BUG-21 · P2 · Retain first-step combat-damage eligibility (RULE 510.4).**
  `game/engine/combat_mixin.py:_deals_in_step` tests current keywords only. An unblocked 2/2
  deals four damage if its first-strike-granting lord dies in the first step. Remember exact
  combatant visits and their initial eligibility; regular damage permits initially ordinary
  combatants and remaining creatures that currently have double strike. Coordinate with BUG-20.

- **BUG-22 · P1 · Derive combat consequences from completed damage (RULE 120.3f/615.1/702.2b).**
  `game/engine/combat_mixin.py:_apply_combat_damage` uses assignments after prevention/replacement:
  Fog still grants lifelink life and emits aggregate player-hit events; partial prevention grants
  too much life; a prevented deathtouch hit kills a creature with old marked damage. Use actual
  completed source/recipient/amount receipts, including redirection and suspended replacement
  choices, and aggregate only successful hits. Coordinate shared finalization with BUG-23.

- **BUG-23 · P1 · Apply lifelink/deathtouch to noncombat damage (RULE 120.3f/702.2b).**
  `game/rules/damage_death_mixin.py:_finish_damage` omits both consequences: three damage from a
  lifelinker gains no life, and one damage from a deathtouch source leaves a 4/4 alive. Finalize
  source-ability consequences in the shared successful-damage path, without duplicating combat
  or fight handling; cover prevented damage as well as actual hits. Coordinate with BUG-22.

- **BUG-25 · P1 · Process multiplayer departures immediately (RULE 800.4a).**
  `game/rules/sba_mixin.py` defers departing players' objects/effects through `pending_leave_ids`
  until `begin_turn`; a conceding player's permanents still affect the ongoing turn. Perform the
  ownership/control/stack departure sequence immediately, including ending control effects and
  removing abilities controlled by the departed player. Keep review snapshots independent of live
  rules state; cover concession, loss, stolen objects and priority transfer in a three-player game.

- **BUG-26 · P2 · Let the controller choose the surviving legend (RULE 704.5j).**
  `game/rules/sba_mixin.py:_apply_legend_rule` always keeps the first copy, discarding even a later
  copy with more counters. Add resumable choices for conflicting legend groups and apply the
  chosen departures in the simultaneous SBA batch. Coordinate with BUG-14.

- **BUG-31 · P1 · Resolve ninjutsu as an activated ability (RULE 702.49a/602/117).**
  `game/engine/combat_mixin.py:ninjutsu` immediately puts the Ninja onto the battlefield with no
  stack item and rejects legal activation after damage. Use hand-zone reveal/return costs,
  ordinary stack resolution, response priority and split-second restrictions; allow activation
  whenever a qualifying unblocked attacker exists and its controller has priority. Coordinate
  end-of-combat timing with BUG-30.

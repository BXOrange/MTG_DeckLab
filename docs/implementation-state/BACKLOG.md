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

  > **Ids:** `PAR-1`…`PAR-150` are taken — grep `Done_Backend.md` before reusing one. First free:
  > **`PAR-151`**; next free `MEC`: **`MEC-114`**; next free `ENG`: **`ENG-53`**; next free `VIS`: **`VIS-15`**. A new engine primitive found along the way files
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
> PAR-99…105 counts confirmed at PV 413 (2026-09-16, vs the 56 saved decks in `deck_coverage.py`),
> re-verified at PV 447 (2026-09-21). Re-run `parser_probe.py blocked` before starting.

- **PAR-109 · Residue of the static/activated-ability batch.** Brad Boimler's until-EOT counter replacement;
  Worldknit's card-pool condition; "can't be regenerated" leftovers (Bone Shaman, Lim-Dûl's Cohort); Desolation of
  Smaug's "spend only to cast Dragon spells"; Luxior's per-counter bonus; Atalya's modal `{X}, {T}` body.

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
- **PAR-147 · Dice grammar axes.** The engine exists (`RollDieEffect`, `roll_die`, `roll_dice_modifier`); 68
  Commander-legal cards carry roll text, 38 with only roll clauses unclaimed. Axes, each a separate grammar
  piece: a single die whose result is an amount/filter operand (21 cards, e.g. Bag of Devouring, Bag of
  Tricks, Ebony Fly); d20 table rows `1—9 | …` (18, Aberrant Mind Sorcerer) — first check whether the IR can
  express a table block; roll N dice and choose/ignore (10, the `Endeavor` cycle); "whenever you roll" /
  "if you would roll" (12). Risk: "the result" must read the kept die after Krark's Other Thumb. Verify with
  `engine_bench.py`, not parse verdicts.
- **PAR-149 · Bucket B candidates to validate before any handler.** Report counts at PARSER_VERSION 584, not yet
  checked with `blocked`/`card`: "cast this spell only during combat / before blockers / the declare blockers
  step" (15, three phrasings), "when enchanted creature/land dies, return that card …" (6 + 6), emblem with a
  quoted ability (48 cards, only 5 SOLO — Dack Fayden, Liliana the Last Hope, Tezzeret Artifice Master,
  A-Saheeli, The Capitoline Triad; the rest are blocked by other planeswalker abilities). Decision open: which
  of these earn a handler; the emblem case is weak on SOLO yield.
- **PAR-150 · Multi-target ("up to N", "up to X") for gain control, goad, counter and keyword grants.** The
  single-target forms are `MODELED`; the plural forms stay `UNMODELED` because those handlers don't opt into
  `_MULTI_TARGET_QUANTIFIER` (destroy/exile/tap/untap/return/counters/damage/pump/can't-block already do;
  `TargetSpec.count`/`count_max`/`count_selector` are effect-agnostic, so the open part is each effect's
  `count`/`target_count` param and slicing). Measured at PARSER_VERSION 611, SOLO blockers: gain control "up to
  N target creatures" (4: Hideous Taskmaster, Jace Ingenious Mind-Mage, Rangers of Ithilien, The Super Hero
  Civil War), per-opponent "goad up to 1" (2: Havoc Eater, Sontaran General), "up to N/X target creatures
  gain `<keyword>`" (3: Invisible Force Field, Mogis's Marauder, Voyager Drake), "counter up to N target spells
  [and/or abilities]" (5: Double Negative, Katara's Reversal, Repel Intruders, Repulsive Mutation, Tishana's
  Tidebinder). Verify with `engine_bench.py`, not parse verdicts.

## MEC — Game mechanic

- **MEC-111 · Rooms: door state and unlocking (RULE 709.5).** Rooms have no locked/unlocked door state — casting a Room *is* its
  door unlocking, only the front half's text is cached, and nothing can unlock a door later, count "fully unlock", or cast either
  half. 30 cached Room cards plus Blu Mansion Prince, Fear of Sleep Paralysis, Secret Arcade and the "unlock" payoffs. Needs the
  cache to hold both halves (a `Card` schema change wipes the cache; `import_bulk.py --reseed-only` restores it).
- **MEC-112 · "You may choose new targets for the copy" (RULE 707.10c).** Spell/ability copies always keep the original's targets
  (`copy_spell`/`copy_ability` take a caller-supplied `new_targets`, no interactive choice exists). 225 cached cards carry the
  text (e.g. Gogo, Sevinne's Reclamation); the 78 already covered silently take the default.
- **MEC-113 · "Until ~ leaves the battlefield" as a duration (RULE 610.3).** The exile family uses the legacy linked-exile leaves
  trigger (`return_linked_exile`, 10 hand-authored cards plus the parser's mass-exile rows): the return is respondable, and an
  enters trigger still exiles when the source already left. ~143 cached cards use the wording (Portable Hole, Auron, Summon: Ixion).

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

- **BUG-1 · An "Equip …" line is claimed as a keyword line and its text silently dropped.** The
  segmenter reads any line starting with "Equip" as a keyword line (`keyword_line=True`), so "Equip
  abilities you activate [that target X] cost {N} less to activate." and "Equip {N}. This ability costs
  … less to activate …" emit no spec: Bureau Headmaster, Bladehold War-Whip, Cloud Planet's Champion,
  Dwarven Mauler, Helitrooper, Plate Armor / A-Plate Armor and Warrior's Blades are `MODELED` without
  their equip-cost discount. Fix: fail the line closed unless it is a bare equip cost, then give the
  discount its own row (activation costs have no `targets` yet — see Kopala/Strong Back).
- **BUG-2 · "target player draws N cards and loses N life" in a reflexive / exploit trigger.** The subject-less
  "and loses …" now carries `previous_subject` (direct triggers and spells are right: Vault Plunderer, Bloodgift
  Demon); check that Unscrupulous Contractor's reflexive trigger and Fell Stinger's exploit trigger make the
  *targeted* player lose the life, not the controller.

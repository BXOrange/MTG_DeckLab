# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. The log is one
  line per milestone, newest last.
- **On closing the ticket, delete its whole block** (the narrative belongs in
  `Done_Backend.md` / `Done_Frontend.md`, open residue in `BACKLOG.md`). With no ticket in
  progress this file is just this header and the empty template — no ticket id, no log.

Block template (copy below the line, fill in):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Log:** <YYYY-MM-DD HH:MM — one line per milestone>
```

---

## PAR-119 · Composed trigger-head grammar — remaining axes

- **Started / last update:** 2026-09-29 / 2026-09-29 (state reconstructed from commit
  `d2967b79` "PAR-119 Intermediate", which shipped code without updating ticket or worklog)
- **Goal of this run:** axis (a) batch quantity — "whenever one/N or more `<objects>`
  enter / die / leave / are discarded / deal combat damage". Then the rest of (c)/(d) and
  the legacy-row migration.
- **Done (built + tested, in `d2967b79`):**
  - (b) attack leftovers — total power, "with your commander", "with counters on them",
    "~ and another legendary creature", "that many" off an attack batch
    (`game/trigger_quantities.py` captures the matching attackers per ability, RULE 603.2),
    Arthur's end-of-combat return. Tests: `test_par119_attack_batch_head.py`.
  - (c) "enters from a graveyard / exile" (every ENTERS emitter now supplies an origin).
    Tests: `test_par119_zone_origin.py`.
  - (d) "you're dealt damage", opponent combat-damage head, proliferate, "taps a land for
    mana", draw exclusions ("except the first N … in each draw step").
    Tests: `test_par119_player_event_head.py`.
  - (e) ordinals ("first spell on each opponent's turn"), magecraft "or copies", "that has
    an adventure"; "during an opponent's turn" now controller-relative (the migration's
    named defect). Tests: `test_par119_cast_trigger_grammar.py`.
  - "otherwise" residue — Insatiable Appetite / Pippin's Bravery / Lorehold Excavation.
    Tests: `test_par119_otherwise.py`.
- **In progress:** — (clean point: slices 1–3 of axis (a) done, documented, suite green;
  all uncommitted — the user commits)
  - Slice 1: object batches — `EVENT_BATCH`, `GameState.simultaneous`, batch head, typed
    graveyard exits (v502). Slice 2: discard batches + multi-pick hold (v503).
  - Slice 3: combat-damage batch head over `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
    (`object_trigger_head._parse_combat_damage_batch_head`, `binding.core.
    _contributor_members`, engine stamps `contributor_amounts`), plus the shared type noun
    "ninja or rogue creatures" (`characteristic_phrase._alternation`) (v504). +9;
    whole-cache spec diff 0 lost / 0 changed. Tests: `test_par119_combat_damage_batch.py`.
  - Cumulative vs HEAD: +48 modeled. Coverage 51.2 % (17,837), Commander-legal 53.8 %
    (17,132). Done_Backend "PAR-119 (a)" entry covers all three slices. BACKLOG PAR-119
    (a) narrowed; new ticket PAR-130 ("target `<X>` that player controls" scope).
- **Next step:** the user picks: (1) **PAR-130**, the "that player controls" target-scope
  slot: 102 SOLO, the biggest lever found. It needs the trigger's antecedent at body-parse
  time (damaged player vs "for each opponent" vs prior target player). (2) The rest of
  PAR-119: "for each of them" over batch members (Kambal, Mythweaver Poq, Twilight
  Diviner), the "sacrifice N or more" scope for cost paths, combat-damage subjects ("that
  entered this turn", "goaded", "face-down"), then the legacy-row migration (incl. the two
  bare combat-damage `_PLAYER_TRIGGER_CONDITIONS` rows and the hand-authored
  ``contributor_*`` flags onto `contributors`).
- **Decisions:**
  - Bare "~ <verb>" is a legal object-head subject (same spec as the legacy self row; the
    head adds `from_zone`). The fails-closed pin was stale → moved to the positive table.
  - **Batch design (RULE 603.2c):** no per-object merging of pending triggers. Instead an
    aggregate `EVENT_BATCH` event ``{"batch_of": <EventType name>, "members": [<the original
    per-object GameEvents>]}``, fired once per *simultaneity scope* per batched type
    (ENTERS_BATTLEFIELD, LEAVES_BATTLEFIELD, DIES, DISCARD_CARD). Scope = one instruction's
    apply (`_apply_effects_partitioned`, so "create two tokens" / "destroy all" = one batch,
    two separate "create a token" sentences = two), the SBA pass (RULE 704.3), nested scopes
    merge into the outermost; an event outside any scope is its own 1-member batch. Same
    pattern as MEC-78's `CARDS_LEFT_GRAVEYARD` / `ATTACKERS_DECLARED`.
  - Trigger spec: ``{"event": "EVENT_BATCH", "batch": {"of": "DIES", "min": N},
    "condition": <the normal group condition>}``. The binder builds the *per-object*
    predicate for ``of`` (recursive `_trigger_condition`, so every filter/tail still
    applies) and counts matching members ≥ min.
  - Parser: `object_trigger_head` gets a quantity head "`<n>` or more [other] `<plural
    phrase>` enter/die/leave the battlefield" reusing the head's tail loop.
  - Legacy `_BATCH_ENTER/_BATCH_DIES` rows retired onto the real batch; Frantic Scapegoat
    kept (its "one of the other creatures" = the batch's ``matching_ids``).
  - Combat-damage batch reuses the existing aggregate (already one per controller × damaged
    player, RULE 510.2); the trigger is ``{"contributors": {"min": N}}`` and each contributor
    is re-read as a per-creature combat DAMAGE event, so the singular damage head's
    vocabulary applies. Legacy rows kept for now (player rows run first → no spec churn).
  - Residue deliberately left: "for each of them, … copy of it" over batch members
    (Kambal, Mythweaver Poq, Twilight Diviner), "leave the battlefield without dying",
    "enter without being played", "~ deals x damage to each opponent" (damage grammar).
- **Baselines / artefacts:** PARSER_VERSION 504 (coverage 51.2 %, 17,837 / 34,811;
  Commander-legal 53.8 %, 17,132). Spec baseline of HEAD before this run:
  `scratchpad/p119_base.json` (session-local; regenerate from a HEAD worktree if gone).
- **Known failures:** none at v504 (plain suite 9,133 passed; `--full-cache` tier 9,422 passed).
- **Log:**
  - 2026-09-29 — state reconstructed from `d2967b79`; 287/288 PAR-119 tests green.
  - 2026-09-29 — "~ enters" pin fixed (stale); PAR-119 tests all green.
  - 2026-09-29 — axis (a) slice 1 built: EVENT_BATCH engine + batch head, +30 cards.
  - 2026-09-29 — slice 1 closed out: v502, 51.2 %, suite green, docs synced.
  - 2026-09-29 — slice 2 (discard batches + multi-pick hold) built, +10 cards.
  - 2026-09-29 — slice 2 closed out: v503, 51.2 % (17,828), suite 9,393 green, docs synced.
  - 2026-09-29 — slice 3 (combat-damage batch head) closed out: v504, +9, suite green, docs synced.

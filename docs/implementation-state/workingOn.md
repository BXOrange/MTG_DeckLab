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
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-132 · Dependent target/body follow-up batch

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** re-size every calibrated PAR-132 row (`PARSER_LONG_TAIL.md`, "PAR-132 calibration") with `parser_probe.py` at the current PARSER_VERSION, then land the highest-yield shared shapes via existing primitives.
- **Done (built + tested):** v688 (+8 / -0, 21,788 covered, authoritative 62.2%). (a) Row 2 slice: `for each [nontoken] <type(s)|permanent|card> destroyed/exiled this way, <body>` -> `for_each` over `{"this_way": verb, this_way_nontoken, this_way_type}` (`ForEachEffect._this_way_items`, new `GameContext.destroyed_objects`; `exiled_objects` existed); "its controller creates" -> new `create_token creators="iteration_item_controller"`; item-independent bodies ("you create a Treasure", Canoptek). Cards: Hour of Need, Descent of the Dragons, March of Souls, Rampage of the Clans, Blood Money, Canoptek Scarab Swarm. (b) Row 4/6 slice: "that spell or ability's controller" / "that player" loses life / takes damage under a BECOMES_TARGET head (marker `event_player_events`, `gate._event_player_antecedent_ok`): Ashenmoor Liege, Retromancer. Tests: `backend/tests/test_par132_this_way_loops.py` (6, parse + execute + refusals); `test_par107_114_misc_family.py` adjusted (nontoken form now claimed; multicolored stays unclaimed). Suite 14,303 passed (default) and 14,701 passed (`--full-cache`).
- **In progress:** nothing.
- **Next step:** pick the next row below; start with the `this way` tally axis (largest) or the BECOMES_TARGET body family.
- **Decisions:** selected by the orchestrator (lowest ID among equal eligible PAR tickets; MEC-125 excluded by user). `run_tests.py` needs `--hard-timeout 1500` (suite now ~210s, default 120s kills it).
- **Baselines / artefacts:** snapshot of v687 at /private/tmp/claude-501/par132_base.json (scratch).
- **Known failures:** none.
- **Residue (sized at v687, `parser_probe.py blocked`, unclaimed-clause counts, solo/also-blocked):**
  1. `for each X, choose up to one target ... that player controls` announce+body: 4 solo (Decoy Gambit, Kitesail Larcenist, Mega Flare, Tolarian Contempt; Shellshock/Disorienting Choice use the `. ... each of those`/`chosen this way` follow-ups) - needs per-round chosen-set referent, not built.
  2. `this way` family: 52 cards for `creature(s) affected/dealt damage/exiled/destroyed/tapped/chosen this way` (41 solo); 77 solo for the broader for-each/destroyed/exiled/sacrificed/tapped/discarded/returned this way regex. Remaining: tapped/sacrificed/discarded/returned tallies (no engine tally yet), `chosen this way`/`those creatures` (382 cards, 313 solo, diffuse), "its controller reveals/searches" per-object bodies (Chaos Mutation, Chaotic Transformation, Indomitable Creativity, From the Ashes), color-qualified counts (Culmination of Studies), "that player investigates for each ..." (Declaration in Stone).
  3. prior-target group bodies (Alpha Brawl, Deputy of Detention, Legions to Ashes): not sized yet.
  4. trigger heads: `beginning of combat on each opponent` 3 solo (Champions of Minas Tirith, Fight or Flight, Web of Inertia: body-blocked: pay-or-cannot-attack, piles); `becomes the target of a spell or ability` 25 cards (23 solo, now ~21) - heads already parse, bodies missing ("counter that spell or ability" + "for the first time each turn" Glyph Keeper cluster, "that spell or ability's controller sacrifices a land", quoted grants Kira/Nadu); `defending player` 156 cards (130 solo), mostly body-side; `from an instant or sorcery` 0.
  5. atomic combat heads: `enters ... attacking` 4 solo; blockers/attached subjects not re-sized.
  6. `that much` 125 (99 solo); `for as long as ~ remains on the battlefield` 16 (15 solo; control-duration cluster); Commando Raid quoted wrapper not sized.

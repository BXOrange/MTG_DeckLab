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
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-147 · Dice grammar axes

- **Started / last update:** 2026-10-12 / 2026-10-13 00:10
- **Goal of this run:** parser grammar onto the existing dice engine (RULE 706): result as amount/gate, results tables, roll N and choose, roll heads.
- **Done (built + tested, `backend/tests/test_par147_dice_grammar.py`, 45 tests):** result-as-amount sentences (`segmenter._die_x_rest`/`_bind_x_specs`); result gates -> `amount_compare` (+ `rolled_doubles`/`any_die_result`, "otherwise" = negated sibling, "that much"); per-die `EventType.DIE_RESULT` heads + `event_maximums`; as-enters roll + counters; `die_results`/`die_choice` amounts, "for each even/odd/different result"; `roll_die` `count: "x"`/`count_amount`/`choose` (Endeavor choice via `choose_die_result` continuation, die state kept in deferred entry `die_state`); results-table block generalised (label/pre-effect/cost headers via `segment_line`, "indicated effect" style, "N or less"); mill X, +X/+0. PARSER_VERSION 634 + lock written.
- **In progress:** — (milestone 1 committed at PV 634)
- **Next step:** the roll-modifier axis ("roll a d20 and add/subtract <amount>": `RollDieEffect.modifier` + parser — Diviner's Portent, Revivify, Song of Inspiration, Danse Macabre, Gale's Redirection, Wyll's Reversal, The Deck of Many Things); size with `parser_probe.py blocked` first. Note: after a PARSER_VERSION bump `TestManaMaximizerBot::test_plays_lands_and_taps_them_but_never_casts` can take ~20s on a cold parse cache.
- **Decisions:** "that result" only reads the Endeavor choice (or equal dice); never the die sum. Mana-ability tables (Jack-in-the-Mox) stay unmodeled (RULE 605.3b). Table rows may not announce targets.
- **Baselines / artefacts:** PV 633 coverage 21,156 -> PV 634 21,225 / 35,046 (60.6%); probe diff +69 / -0. Snapshot `%TEMP%\par147_base.json`.
- **Known failures:** pre-existing slow test — deselect `tests/services/test_bots.py::TestSearchChoices::test_a_fetch_land_is_not_wasted_declining_its_own_search` on whole-tier runs.
- **Residue:** (1) roll modifier "and add/subtract <amount>" (Diviner's Portent, Revivify, Song of Inspiration, Danse Macabre, Gale's Redirection, Wyll's Reversal, Deck of Many Things) - needs `RollDieEffect.modifier` + parser; (2) table rows/headers needing other primitives: Aberrant Mind Sorcerer, Druid of the Emerald Grove, Journey to the Lost City, Contraband Livestock, Power of Persuasion, Spiked Pit Trap, Cone of Cold, Thunderwave, Myrkul's Edict, Swarming Goblins ("of those tokens"), Treasure Chest, Wizard's Spellbook, Loathsome Troll (graveyard activation), Iron Mastiff, Lae'zel's Acrobatics, Delina; (3) Endeavor halves: Arcane (cast with MV <= other result), Grave (return with counters), Wild (search X); (4) result-reading one-offs: Arden Angel (graveyard upkeep trigger), Krazy Kow, Sly Spy ("that player" under damage trigger), Bag of Tricks/Devouring, Time Out, Underdark Rift, Ebony Fly, Hammer Helper, Strength-Testing Hammer, Sword of D&D / Hours, Mr. House, Priority Boarding, Resolute Veggiesaur, Jumbo Imp end step ("remove X counters"); (5) Krark's Other Thumb / advantage-style replacements (MEC-117); (6) non-Commander-legal Un-cards (contraption "difference between results", assemble, attractions, stored results).

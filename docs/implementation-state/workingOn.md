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

- **Started / last update:** 2026-10-12 / 2026-10-13 01:20
- **Goal of this run:** parser grammar onto the existing dice engine (RULE 706): result as amount/gate, results tables, roll N and choose, roll heads.
- **Done (built + tested, `backend/tests/test_par147_dice_grammar.py`, 45 tests):** result-as-amount sentences (`segmenter._die_x_rest`/`_bind_x_specs`); result gates -> `amount_compare` (+ `rolled_doubles`/`any_die_result`, "otherwise" = negated sibling, "that much"); per-die `EventType.DIE_RESULT` heads + `event_maximums`; as-enters roll + counters; `die_results`/`die_choice` amounts, "for each even/odd/different result"; `roll_die` `count: "x"`/`count_amount`/`choose` (Endeavor choice via `choose_die_result` continuation, die state kept in deferred entry `die_state`); results-table block generalised (label/pre-effect/cost headers via `segment_line`, "indicated effect" style, "N or less"); mill X, +X/+0. PARSER_VERSION 634 + lock written. **Milestone 2 (PV 635, `test_par147_dice_grammar.py` 60 tests):** roll modifier `RollDieEffect.modifier`/`modifier_amount`/`modifier_subtract` + `RulesEngine.roll_die(modifier=)` (RULE 706.4: `die_result`/DICE_ROLLED `total` modified, `die_results`/`natural_results`/`highest` natural; single-die roll modifies that die's DIE_RESULT) -> Diviner's Portent; Endeavor halves: search count `X`/fixed N (`_SEARCH_CRITERIA`), untargeted reanimate "with N/X counters on it" (`then_effects` on the pick), `free_cast_from_hand` `instant_sorcery_only` (+`during_resolution`), die rewrites for "a number of … equal to", "mana value less than or equal to the other result", "with a number of counters equal to" (`segmenter._SEARCH_NUMBER_DIE_RE`/`_CAST_MV_DIE_RE`/`_RETURN_COUNTERS_DIE_RE`), `max_mana_value` is an X param; table rows now build through `composition._build` (announced X + row conditions); "create N of those tokens" rows (`gate._expand_of_those_tokens`) -> Swarming Goblins. Unlocked +14 vs PV 634: Arcane/Grave/Wild Endeavor, Diviner's Portent, Swarming Goblins, plus search-count collateral (Diabolic Revelation, Grow from the Ashes, Hexhaven Invigorator, Nylea's Intervention, Omnispell Adept, Planar Engineering, Sporocyst, Surtland Elementalist, Wildfire Eternal).
- **In progress:** — (milestone 2 committed at PV 635)
- **Next step:** the target-header table rows (Residue 2: "its controller creates a token" — Contraband Livestock; "~ deals N damage to that creature" — Spiked Pit Trap; "gain control of it until the end of your next turn" — Power of Persuasion); size with `parser_probe.py blocked` first. Never point an archived/older tree at the production `backend/cache/db/cards.db` (a schema-hash mismatch wipes it; recovery: `backend/scripts/import_bulk.py --reseed-only`).
- **Decisions:** "that result" only reads the Endeavor choice (or equal dice); never the die sum. Mana-ability tables (Jack-in-the-Mox) stay unmodeled (RULE 605.3b). Table rows may not announce targets.
- **Baselines / artefacts:** PV 633 coverage 21,156 -> PV 634 21,225 / 35,046 -> PV 635 21,239 / 35,095 by the probe (60.52%); probe diff vs 634 +14 / -0. Snapshots `%TEMP%\par147_base.json` (633), `%TEMP%\par147_634.json`. Do NOT run an archived copy of the tree against `backend/cache/db/cards.db`: a different schema hash wipes the card table (reseed with `backend/scripts/import_bulk.py --reseed-only`, offline).
- **Known failures:** pre-existing slow tests (~19s standalone, can trip the 20s timeout, especially under CPU load) — deselect both on whole-tier runs: `tests/services/test_bots.py::TestSearchChoices::test_a_fetch_land_is_not_wasted_declining_its_own_search` and `tests/services/test_bots.py::TestManaMaximizerBot::test_plays_lands_and_taps_them_but_never_casts` (18.7s on 93403967 without changes). Full tier needs `--hard-timeout 3000`.
- **Residue:** (1) roll-modifier cards needing a referent primitive of their own: Revivify (graveyard cards "put there from the battlefield this turn" count + mass return), Song of Inspiration ("total mana value of those cards" over up-to-2 targets), Gale's Redirection (exiled spell's mana value + cast the exiled spell), Wyll's Reversal (choose new targets / copy a spell with targets), Danse Macabre ("toughness of the creature you sacrificed this way" + return from the graveyard creature cards put there this way), The Deck of Many Things (random graveyard return, "discard your hand" gate, "when that creature dies, its owner loses the game"); (2) table headers/rows needing other primitives: header "exile/choose target X, then roll" parses, rows do not: "its controller creates a token" (Contraband Livestock), "~ deals N damage to that creature" (Spiked Pit Trap), "gain control of it until the end of your next turn" (Power of Persuasion); Aberrant Mind Sorcerer, Druid of the Emerald Grove (search then reveal then rows), Journey to the Lost City, Cone of Cold ("don't untap during their controllers' next untap steps", "creatures enter tapped until your next turn"), Thunderwave ("choose a creature … each creature not chosen"), Myrkul's Edict ("choose an opponent. that player sacrifices", greatest power), Treasure Chest, Wizard's Spellbook, Loathsome Troll (graveyard activation), Iron Mastiff, Lae'zel's Acrobatics, Delina; (3) result-reading one-offs: Arden Angel, Krazy Kow, Sly Spy, Bag of Tricks/Devouring, Time Out, Underdark Rift, Ebony Fly, Hammer Helper, Strength-Testing Hammer, Sword of D&D / Hours, Mr. House, Priority Boarding, Resolute Veggiesaur, Jumbo Imp, Clay Golem ("monstrosity X, where X is the result"), Pair o' Dice Lost, Bucknard's Everfull Purse, Maddening Hex; (4) Krark's Other Thumb / advantage-style replacements (MEC-117); (5) non-Commander-legal Un-cards (contraption "difference between results", assemble, attractions, stored results, Souvenir T-Shirt, Goblin Girder Gang, Celebr-8000, Free-Range Chicken). Existing quirk noticed: an untargeted "return a creature card … to the battlefield. Put N counters on it." as two sentences leaves the counters off (previous_subject after an auto-picked single candidate); the with-counters clause now rides `then_effects` instead.

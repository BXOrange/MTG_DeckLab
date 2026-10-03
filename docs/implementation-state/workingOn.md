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
- Keep it terse and current — replace stale lines instead of appending. Keep only the current resumable state; session logs belong in unversioned temporary files.
- **On closing the ticket, delete its whole block** (the narrative belongs in
  `Done_Backend.md` / `Done_Frontend.md`); a ticket is closed only once its residue is done
  too. With no ticket in
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
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PLAY-ALL · Make every saved deck playable

- **Started / last update:** 2026-10-01 / 2026-10-03
- **Goal:** Bring every non-cube saved deck to N/N in `scripts/deck_coverage.py`; Commander Cube last and optional.
- **Done:** Step 0 (War Room and alternate-name resolution) and Step 1 handler batches completed. General parser results are documented in `Done_Backend.md`. Completed deck coverage: Goblins 39/39, yshtola 97/97, Hydranten 81/81, Raggadragga 84/84, Kodama 75/75, Wick Snail Boom 84/84, Counter Intelligence 94/94; SpongeBob's last recorded missing card (Gogo) is authored. Individual card implementations and their limitations live in `game/card_catalogue/` and `tests/game/catalogue/cards/test_*_deck.py`, not in the Done catalogue.
- **In progress:** Oops! All Night's Whispers 88/99; World Shaper 83/87. No half-built change recorded.
- **Next step:** Continue Oops! with the 11 cards below. From `backend/` with the project venv, run `python scripts/deck_coverage.py --uncovered "Oops! All Night's Whispers"`. If its decklist is absent, inspect the listed cards in the cache individually; do not treat a missing decklist as completed coverage. Before authoring, check existing parser claims and engine primitives, and size shared clause families with `parser_probe.py blocked`.
- **Decisions:** Prioritize shared parser axes, then decks by marginal cost. Reuse existing primitives before adding new ones. Hand-author isolated gaps; Alchemy is a permanent non-goal. Coverage N/N means MODELED or AUTHORED, not proof that every printed ability is rules-exact.
- **Baselines:** Last recorded parser version 591; the global coverage figure in `CLAUDE.md` is still the v586 measurement and needs a fresh `scripts/coverage_report.py` run. Latest recorded full pytest: 10,712 passed, 316 skipped (historical result, not rerun for this documentation cleanup). Decklists for the larger decks were absent on this PC; their recorded counts came from the card cache and must be remeasured when decklists are available.
- **Known failures:** Intermittent random-planar-die failure in `tests/test_casual_variants.py::test_a_phenomenon_planeswalks_the_table_straight_on`; previously passed alone and in repeated full-file runs.

### Residue · cards and remaining deck order

- **Oops! All Night's Whispers (88/99):** Breach the Multiverse; Coiling Rebirth; Fable of the Mirror-Breaker // Reflection of Kiki-Jiki; Living Death; Marchesa, Dealer of Death; Palantir of Orthanc; Prismari the Inspiration; Ripples of Undeath; Scholar of the Lost Trove; Sewer Nemesis; Victimize.
- **World Shaper (83/87):** Braids, Arisen Nightmare; Eumidian Wastewaker; Evendo Brushrazer; Exploration Broodship.
- **Then, last recorded missing-card counts:** Riveteer Rampage 19; Miracle Worker 20; Death Toll 22; Jump Scare! 22; Shorikai Vehicles 24; Hope to the last 25; Endless Punishment 26; Turtle Power! 28; then Commander Cube.
- **Other decks from the original plan, not subsequently accounted for:** Jeskai Striker; Family Matters; Animated Army; Abzan Armor; Eternal Might; Sultai Arisen; Mardu Surge; Scions & Spellcraft; Peace Offering; Living Energy; Temur Roar; Revival Trance; Counter Blitz; Limit Break. Their October 1 counts are stale; remeasure before ordering work.

### Residue · known correctness gaps

Coverage completion does not close these recorded limitations; confirm them against the current card files before fixing them.

- **Counter Intelligence:** Depthshaker Titan does not grant melee; Emry's permission uses flashback (different unresolved-stack destination); Resourceful Defense moves all counters rather than allowing an arbitrary number.
- **Kodama:** Roaring Earth's animation omits green; Springheart Nantuko's copy branch does not check that the attached creature is controlled by you; Defiler of Vigor's optional life payment is chosen by the mana solver rather than prompted.
- **yshtola:** Defiler of Dreams uses the same payment simplification; Emet-Selch's graveyard permission lasts the turn rather than being used during trigger resolution; source-less counters (including Ward) do not attribute a countering controller for Baral.
- **Raggadragga / Hydranten:** Turntimber's land back face is not authored (only front-face cache text); Yarus returns creatures face up directly, altering ETB/turn-face-up behavior; Genesis Hydra's cast trigger is a resolution payoff; Runadi's extra entry counters use a standing grant rather than a respondable trigger.
- **Wick Snail Boom:** Chameleon's Mayhem is not supported; Teferi's Time Twist adds its creature counter after entry rather than as it enters.
- **SpongeBob:** The Prismatic Bridge back face is not authored (cache limitation); Atraxa's distinct-type picker rejects some legal combinations of multitype cards; Gogo's copied abilities retain targets.
- **World Shaper:** Eumidian Hatchery's mana counter rider is a stack trigger; Moraug untaps when its landfall trigger resolves rather than at the start of the additional combat.

### Residue · follow-ups outside individual card coverage

These were recorded as unticketed follow-ups; inspect existing backlog entries before creating duplicates.

- Fix Killian's `reduce_if_targets` filter (`is_creature` is ignored; use `card_type: creature`).
- Add parser axes for Case's instant/sorcery-count solve condition, Defilers' permanent-spell filter, generic mana-ability counter riders, counter/pump-then-fight, flicker with riders, multi-event attack/block/target heads, equipped-creature X pump, and Turn Inside Out's temporary dies trigger.
- Apply the legendary-sorcery cast gate to Jaya's Immolating Inferno and other applicable entries.
- Revisit Magda, the Hoardmaster: `CRIME_COMMITTED` already exists; its documented engine blocker is stale.
- Integration coverage still limited for Patrolling Peacemaker (event fired by hand), Kellan (no real graveyard cast), and Giggling Skitterspike (BLOCKS not exercised in its deck test).

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
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
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
- **Done (built + tested, 23 new tests in test_par249_token_names_creating_card.py):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-258 · "Differently named lands you control" as a dynamic amount

- **Started / last update:** 2026-11-10 / 2026-11-10
- **Goal of this run:** close PAR-258: the differently-named-lands count in every slot the 15 Star Trek cards use (amounts, conditions, activated-ability cost reduction).
- **Done:** probe at 871: 19 cards in unclaimed clauses (16 solo). Slot fixes: `count_phrase.parse_count_phrase` reads "differently named <phrase>" (distinct name) so every "where x is the number of ..." / "equal to" / condition / cost-reduction reader gets it; `segmenter` activated "this ability costs {X} less to activate, where X is the number of <phrase>" -> `ActivationCost.dynamic_reduction` (engine already existed); "you have no maximum hand size until your next turn" row (`keyword_actions.py`); "If X is N or more, <rider>" after a pump `where x` head (Praxis) as bind + `if_else` / `amount_compare`.
- **In progress:** full-pool snapshot diff, tests, engine runs, PARSER_VERSION bump.
- **Next step:** run `parser_probe diff` against the base snapshot (scratchpad `base.json`), then bump PARSER_VERSION 872 + history + lock, engine_bench runs, tests, both test tiers.
- **Decisions:** runs in parallel with the Star Trek singletons worker: no edits under `game/card_catalogue/`, `singletons.md` or the status locales. Left residue (bespoke multi-clause bodies, not the shared slot): Branching Timeline, Commander Spock, Ensign Pavel Chekov, Lieutenant Nyota Uhura, Chief Montgomery Scott (fail even with plain "lands"), Seven of Nine (MEC-141 + permanent base-P/T set), Warp Speed (PAR-259), Species 8472, Euroakus.
- **Baselines / artefacts:** PARSER_VERSION 871; ticket: 15 touched / 13 only.
- **Known failures:** none recorded.
- **Residue:** see Decisions.

## Singletons · Star Trek (TRK + TRC) one-offs

- **Started / last update:** 2026-11-10 / 2026-11-10
- **Goal of this run:** hand-author self-contained cards from the 73-row Star Trek section of `singletons.md`, in batches; remove each from the queue only after a real-engine run.
- **Done (batches A-C, 22 cards, real-engine verified via focused tests, rows removed):** Ensign Harry Kim (PAR-260 residue, `power_vs_reference` trigger filter), Khan Despot by Design, Year of Hell, Geordi La Forge Innovator, K'Vort-Class Raider, Red Alert!, Glory to the Empire!, De-evolve, Dahar Master, U.S.S. Enterprise-C, Beckett Mariner, Kes, Jadzia Dax, Merciful Mandate, Fevered Visions, Live Long and Prosper, Temporal Conqueror, Vash, Hologram Stalker, Targ Wrangler, Miles O'Brien, Guinan. Tests: `backend/tests/game/catalogue/cards/test_star_trek_one_offs_{a,b,c}.py`; helpers `backend/tests/support/star_trek.py`.
- **In progress:** none.
- **Next step:** ~51 rows remain; rows with Notes are blocked on a named primitive. Unexamined rows (Dathon, Needs of the Many, Peace in Our Time, Gul Dukat, Door of Destinies, Concerted Effort, Khaaaaaaaaaaaannn!, T'Pring, Unification, Those Old Scientists, The Inner Light, Brazen Bluff, Borg Incursion, Chronomantic Escape, Cmdr. Troi, Captain Kirk, Kai Winn, Nyota Uhura, etc.) still need triage.
- **Decisions:** runs in parallel with PAR-260 in the same tree: catalogue files, their tests, `singletons.md` and status locales only; no edits under `parser/oracle/`, no PARSER_VERSION bump.
- **Baselines / artefacts:** PARSER_VERSION 870; 73 rows queued.
- **Known failures:** none. Verification scope per orchestrator: focused tests + engine_bench per card only (no --full-cache, no full suite).
- **Residue:** Rite of Oblivion skipped (spec.py `_ADDITIONAL_COST_SACRIFICE_TYPES` lacks `nonland_permanent`; parser dir off-limits while PAR-260 ran). Quark, Georgiou, Sylvia Tilly, Daniels, Stonespeaker Crystal, Holo-Engineer skipped with the exact primitive in each singletons.md Notes cell.

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










## Singletons · Star Trek (TRK + TRC) one-offs

- **Started / last update:** 2026-11-10 / 2026-11-14
- **Goal of this run:** hand-author self-contained cards from the 73-row Star Trek section of `singletons.md`, in batches; remove each from the queue only after a real-engine run.
- **Done (batches A-C, 22 cards, real-engine verified via focused tests, rows removed):** Ensign Harry Kim (PAR-260 residue, `power_vs_reference` trigger filter), Khan Despot by Design, Year of Hell, Geordi La Forge Innovator, K'Vort-Class Raider, Red Alert!, Glory to the Empire!, De-evolve, Dahar Master, U.S.S. Enterprise-C, Beckett Mariner, Kes, Jadzia Dax, Merciful Mandate, Fevered Visions, Live Long and Prosper, Temporal Conqueror, Vash, Hologram Stalker, Targ Wrangler, Miles O'Brien, Guinan. Tests: `backend/tests/game/catalogue/cards/test_star_trek_one_offs_{a,b,c}.py`; helpers `backend/tests/support/star_trek.py`.
- **Done (batch D, 9 more, rows removed):** Khaaaaaaaaaaaannn!, U.S.S. Prometheus (prototype), Door of Destinies, U.S.S. Defiant (Mirror Migrant), I'm a Doctor, Not a..., Captain Kirk Boldly Going, The Inner Light, Gul Dukat, Andromedan Automatons. Tests: `test_star_trek_one_offs_d.py` (12).
- **Done (batch E, 2 cards, rows removed):** B'Elanna Torres Scrapper (surveil, optional reveal via ask_player, artifact branch), Euroakus (PAR-258 residue; differently-named-lands token count, Wizard draw + hand-size pump). Tests: `test_star_trek_one_offs_e.py` (6). Triaged and annotated as blocked in singletons.md Notes: Spock, Chekov, Lt. Uhura, Scott, Species 8472, Needs of the Many, Queen's Diamond, Deep Space 9, Peace in Our Time, Concerted Effort, T'Pring, Unification, Brazen Bluff, Chronomantic Escape, Dathon, Extraction Integrant, Immortal Sun, World at War, Ambulatory Reactor, H.M.S. Bounty.
- **In progress:** none.
- **Done (batch F, triage only, 0 authored):** all 13 previously unexamined rows examined and annotated as blocked in singletons.md Notes (All Good Things..., Gwyndala, Hugh, La Forge, Lwaxana, Nog, Q, S.S. Botany Bay, Sulu, City on the Edge of Forever, The Holodeck, Vulcan Mind-Meld, Voex), each with the exact missing primitive. No test_star_trek_one_offs_f.py written (nothing authored).
- **Done (batch G, 2026-11-14, 2 cards, rows removed):** Rite of Oblivion and 70,000 Light-Years from Home. Added `nonland_permanent` to the additional-cost whitelist and extended the existing exile-controller search with optional revealed hand placement. `test_star_trek_one_offs_g.py` plus `test_additional_costs.py`: 44 passed, including actual flashback, illegal sacrifice rejection, stolen targets, cloned search choices, decline without shuffle, target fizzle and existing search defaults.
- **Next step:** 47 Star Trek rows remain (counted after batch G; the previous 47-row estimate was stale). Recheck their blockers against the current engine, starting with linked hand/graveyard exile (All Good Things... and S.S. Botany Bay) or bounded number choice plus MV-only trigger (Nyota Uhura, Communications).
- **Decisions:** focused tests only; no full-cache tier or full suite. Batch G changes only the spec validator under `parser/oracle/`; hand-authored registration supplies coverage, no grammar or parser-version change.
- **Baselines / artefacts:** PARSER_VERSION 870; 73 rows queued.
- **Known failures:** none. Verification scope per orchestrator: focused tests + engine_bench per card only (no --full-cache, no full suite).
- **Residue:** Quark, Georgiou, Sylvia Tilly, Daniels, Stonespeaker Crystal, Holo-Engineer and the other remaining rows retain their individual primitive gaps in `singletons.md` Notes.

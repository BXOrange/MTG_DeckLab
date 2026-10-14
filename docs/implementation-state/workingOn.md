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

## MEC-117 · "Ignore one" flip and roll replacements (RULE 705.3 / 706.x)

- **Started / last update:** 2026-10-14 / 2026-10-14 04:30
- **Goal of this run:** engine replacement + parser rows for Krark's Thumb, Krark's Other Thumb, Ichor Elixir (milestone 1 landed); the interactive keep/ignore pick is still open.
- **Done (built + tested):** milestone 1 (PARSER_VERSION 646, +3, 0 regressed): `ignore_one` replacement (`effects/replacements.py`, kind coin/die/planar, controller-only), `FLIP_COIN` / `PLANAR_DIE_ROLL` pre-events (`models/game/events.py`), `coin_flip` flips N and fires `COIN_FLIP` once, `roll_die` groups each die into 2^n (`ignore_one_doublings` on `ROLL_DICE`), `roll_planar_die` rolls dice+1; Thumbs stack (two → 4 flips / 4 dice per die), ignored results fire no flip/roll/result triggers; parser `catalogue/replacements._IGNORE_ONE_RE`. Tests: `tests/test_mec117_ignore_one.py` (14); `test_par151_coin_flips` Thumb test flipped to modeled. Default 13070 passed / full-cache 13405 passed.
- **In progress:** —
- **Next step:** build the interactive pick (RULE 705.3/706 + the Thumbs' rulings: the player sees all results, then chooses which to ignore). `RulesEngine.coin_flip` / `roll_die` / `roll_planar_die` return plain values mid-resolution, so this needs a pause/resume path: check how other mid-resolution choices resume (`continuations.open_choice`/`resolve_choice`, the PAR-147 "roll two dice and choose one" path, `_resume_library_position`) and whether flip/roll callers can be continuation-driven; keep the current automatic pick as the bot default.
- **Decisions:** milestone shipped with automatic picks: coin keeps a win if any flip won (always the player's best), die keeps the highest of each group (wrong on tables where low is better), planar keeps chaos > planeswalk > blank.
- **Baselines / artefacts:** PARSER_VERSION 646; coverage 21404/35095.
- **Known failures:** none. Use `run_tests.py --hard-timeout 5400`.
- **Residue:** interactive keep/ignore pick (above); "flip three coins and ignore one" variant unclaimed; rerolls / "roll again" not modelled.

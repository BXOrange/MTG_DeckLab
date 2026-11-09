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
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## BUG-59 · Modal activated abilities are unusable outside direct engine calls

- **Started / last update:** 2026-11-09 / 2026-11-09 19:35
- **Goal of this run:** make every modal activated ability playable through `GameSession`, the UI and bots, and keep modes on borrowed abilities.
- **Done (built + tested):** `GameSession._dispatch_activate_ability` forwards `mode`; `continuous.retarget_modes` + borrowed abilities (`_apply_borrowed_activated_abilities`) and `game_status` temp-grant copy keep `modes`/`modes_exhaust` (grants at ~3579 and ~3785 build non-modal abilities from specs, justified); `gameBoardView.js` sends/matches `mode` on every activate path, labels via `modeHint`, drop guard covers activated modes; `tests/test_bug59_modal_activation_session.py` 8 passed; real-browser check on port 8791 (Cratermaker mode 0 killed Bears, Kargan +1/+1 -> 4/2 and mode vanished from menu), server stopped.
- **In progress:** full suite run; then report.
- **Next step:** forward `mode` in `GameSession._dispatch_activate_ability`, send it from every activate path in `gameBoardView.js`, and keep `modes` on borrowed abilities in `continuous.py`.
- **Decisions:** found by the orchestrator while verifying PAR-255. Fixed now rather than queued, because PAR-237 and PAR-255 cards are MODELED but cannot be activated in a real game without it. A permanent with a missing mode must still raise, never auto-pick (RULE 700.2).
- **Baselines / artefacts:** reproduced at `03b433c8`: `apply_action({"type":"activate_ability",...,"mode":0})` on Kargan raises "must choose a mode in 0..2"; Necrotic Ooze with Goblin Cratermaker in a graveyard pays its own sacrifice and nothing happens (`ActivatedAbility` rebuilt without `modes`, `continuous.py` ~4173).
- **Known failures (corrected; final full-cache recheck pending):** none.
- **Residue:** latent targeting quirk, outside scope: `legal_targets` kind `creature` excludes the ability's own source, so Kargan Intimidator cannot target itself with its Coward/trample modes.

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

## PAR-157 · Flicker with riders

- **Started / last update:** 2026-10-16 / 2026-10-16
- **Goal of this run:** Complete the verified bounded flicker/rider family, including composed and paper Un-set cases.
- **Done (built + tested):** Exact exile/Marchesa foundation and first four compositions are committed. Current v665 milestone reuses serializable battlefield-entry batches for ordinary flicker and repeated returns: exact exile records, as-entry choices through clone/undo, simultaneous admission, post-copy typed counters and successful-return continuations. Fortune preserves saddle visits in attack-event data; eager copies restore original identities on a new zone visit. Drive to Work, Now You See Me and Landfill use explicit per-resolution observations and authorized choices. Factored target/timing/entry grammar supports counters, typed counters and tapped returns. Focused gate: 1367 passed, `/tmp/par157-665-focused.log`; physical/API checks and root actual mirror browser pass.
- **In progress:** v665 source frozen for root independent full-cache gate and milestone checkpoint; final ticket completion is not claimed.
- **Next step:** Root full-cache verification and checkpoint. Pause PAR source changes for the separately approved MEC-124 additional-end-step dependency, then resume the remaining semantic matrix and shared return integrations.
- **Decisions:** Reuse existing delayed triggers and entry/dice/choice frames. Another Round reselects each pass. Native/bonus entry counters combine through replacements. Delayed own-upkeep scope is the existing `controller` scope; three-player regression verifies both opponents are skipped. Paper observations are fresh facts, never guessed or cached as printing metadata. Alchemy stays an explicit non-goal.
- **Baselines / artefacts:** Original v664 snapshot `/tmp/par157-before.json`; v665 diff `/tmp/par157-665-probe.log`; scope/matrix `/tmp/par157-worker-scope.md`, `/tmp/par157-worker-current-matrix.json`, additions/rules `/tmp/par157-adversarial-review.md`.
- **Known failures:** None in the frozen focused gate. Root full-cache gate remains outstanding for this milestone.
- **Residue:** Complete all initial 37 cards plus classified additions/adjacent cases. Flickerform/Coffin still need migration from the synchronous host/Aura return helper to interactive batches. Conditional/paid returns, successful-return riders, source-linked pools, transformed bodies and Identity Thief/Niko copy linkage remain; their last battlefield copiable values require more than the existing front-face copy simplification. Y'shtola needs MEC-124. Final full-family semantic audit, measurements/status and ticket closure remain.

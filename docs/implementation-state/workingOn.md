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
- **Done (built + tested):** Initial read-only full-cache sizing identifies 37 paper rider cards, two adjacent delayed-return grammar cases, five explicit Alchemy exclusions and one graveyard-to-hand negative. Independent full-scan auditing additionally checks Landfill and self-transformed-return boundaries before fixing the final matrix. Existing MEC-123/PAR-156 work is closed and committed before this ticket starts.
- **In progress:** Runtime identity foundation frozen: delayed battlefield returns capture exact exile incarnations; immediate/delayed blink reject tokens and changed exile visits. Actual Marchesa retains the original DIES graveyard incarnation and resolving ability controller across source-control changes. Rules-checked focused selection: 57 passed, /tmp/par157-marchesa-rules.log; source remains parser v664.
- **Next step:** Runtime foundation independently reviewed and checkpointed; continue shared return entry data and full rider family. No new rider grammar is claimed yet. Complete raw scan additions (Landfill and transformed-return bodies) before calling the 37-card initial matrix exhaustive.
- **Decisions:** No arbitrary easy subset; counters/face/tapped data precede ETB, delayed returns capture exact exile visits, and post-return riders consume actual returned objects. Paper Un-set facts require explicit observations; Alchemy remains an explicit non-goal.
- **Baselines / artefacts:** Original v664 snapshot /tmp/par157-before.json; /tmp/par157-baseline.log. Scope plan /tmp/par157-worker-scope.md and actual-card matrix /tmp/par157-worker-current-matrix.json are initial candidates, with verifier additions still to classify.
- **Known failures:** None at baseline.
- **Residue:** Full 37-card rider matrix, adjacent grammar cases, independent semantic review, targeted/full-cache/browser checks where applicable, coverage and ticket commit.

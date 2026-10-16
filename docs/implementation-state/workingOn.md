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
- **Done (built + tested):** Exact delayed exile visits and Marchesa graveyard/controller foundation are committed. Shared return-entry API now applies additive/typed counters, tapped/face/controller instructions before ETB and returns actual successful new visits; native loyalty combines with extra counters through replacements. Four authored compositions (Another Round, Lae'zel's Acrobatics, Flickerform, Tawnos's Coffin) reuse existing delayed triggers, dice and serialized choices. Aura groups retain exact exile visits and legal attachments; source attachment LKI is captured at departure. Worker focused checkpoint: 79 passed, `/tmp/par157-entry-checkpoint.log`; independent broader gate: 130 passed across all new tests, planeswalkers, entry counters and existing return families.
- **In progress:** Source frozen for independent checkpoint review. No ordinary rider grammar or full-family completion is claimed yet; parser remains v664.
- **Next step:** Current source independently reviewed/tested and checkpointed. Adapt existing `battlefield_batches` entry-choice continuation for returned objects and their receipts, add shared ordinary rider grammar, and finish the full semantic matrix.
- **Decisions:** Existing delayed-trigger infrastructure is reused; no new delayed-trigger mechanic is needed. Counters/face/tapped data precede ETB; post-return riders require actual successful returns. Another Round reselects each pass. Paper Un-set facts require explicit observations; Alchemy remains an explicit non-goal.
- **Baselines / artefacts:** Original v664 snapshot `/tmp/par157-before.json`; initial scope `/tmp/par157-worker-scope.md`, matrix `/tmp/par157-worker-current-matrix.json`, additions/rules `/tmp/par157-adversarial-review.md`.
- **Known failures:** None in the frozen focused checkpoint; full-cache suite not yet run for this milestone.
- **Residue:** Full 37-card initial matrix plus classified additions and adjacent grammar. Shared return path still needs interactive as-entry handling and general simultaneous entry batching; Fortune requires exact saddler visits preserved in attack-event data; Y'shtola needs its additional end step. Independent semantic review, full-cache/runtime/browser checks where applicable, coverage and final ticket commit remain.

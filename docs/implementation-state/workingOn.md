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
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## MEC-126 · Target-seeded shared-characteristic groups

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** Compose one announced target with an untargeted group sharing a reference characteristic, through ordinary effect bodies.
- **Done (built + tested):** Read-only sizing confirms ten unmodeled Radiance cards; existing creature-type-sharing predicate and generic choices/continuations identified.
- **In progress:** Disjoint engine-only primitive stage; parser/registry hookup waits for PAR-168 acceptance.
- **Next step:** Worker: implement the shared color-sharing predicate and target-seeded group composition with runtime regression tests, without editing files owned by the active support-policy worker. Then wire ordinary grammar and registry and run full acceptance.
- **Decisions:** Seed target and ability source are separate references. Multicolor intersection is not transitive; colorless seeds keep only themselves. Group members are not separately targeted. Reuse ordinary body/choice capabilities; no per-card adapters.
- **Baselines / artefacts:** Worktree /tmp/mtg-par157-mec-audit, isolated cache/data as PAR-168.
- **Known failures:** Existing selectors cannot seed from an announced target. Existing per-recipient choose-color protection would prompt multiple times for a group.
- **Residue:** Shared primitive, single group color-choice composition, grammar/binder, real-card runtime matrix, coverage and independent verification.

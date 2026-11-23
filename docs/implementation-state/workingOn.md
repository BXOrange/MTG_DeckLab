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
- **Done:** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <the exact next action a fresh session takes>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-292 · Library inspection and search

- **Started / last update:** 2026-11-23 / 2026-11-23 13:10
- **Goal of this run:** milestone M1 only — dynamic search qualities ("with the same name as <ref>", "mana value equal to <amount>", ~18 cards at v912) via a dynamic bound in `filter_slots.quality_criteria` (PAR-284's amounts have landed), plus the named PAR-285 / PAR-321 search shapes it reaches. The rest of the family stays open.
- **Done:** —
- **In progress:** —
- **Next step:** re-scan the `P2 Bibliothek` package with `find_fragments.py` and size the dynamic-quality sub-cluster with `parser_probe.py blocked`; then build it.
- **Decisions:** family ticket worked one sub-cluster per milestone; worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; next `--full-cache` batch after 5 iterations (PAR-326 was iteration 1 of this batch).
- **Baselines / artefacts:** coverage 26,652 / 35,493 at parser 1026 (probe).
- **Known failures:** —
- **Residue:** the rest of `P2 Bibliothek` (see BACKLOG.md PAR-292).

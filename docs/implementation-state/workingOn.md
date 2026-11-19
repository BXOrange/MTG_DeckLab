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

## PAR-289 · Continuous statics

- **Started / last update:** 2026-11-19 / 2026-11-19
- **Goal of this run:** sub-cluster `P2 Statische Dauereffekte` by slot and build the largest clean sub-clusters milestone by milestone.
- **Done:** (nothing yet)
- **In progress:** M1: sub-cluster the family by slot (subject, condition, granted effect) and build the largest clean group.
- **Next step:** read the P2-static sentences from `backend/data/exports/offene-fragmente-2026-11-19-v1003-vollpool-zuordnung.jsonl`, group them by the missing slot (subject phrase, "as long as" condition, granted characteristic / keyword / ability, layer), rank by solo cards, then build the top group.
- **Decisions:** one commit per milestone; the orchestrator runs `--full-cache` every fifth loop iteration and before close. A static is only modeled if the engine applies it in the right layer (RULE 613) on the real card, stops applying when its condition ends, and does not affect a same-type bystander outside its subject.
- **Baselines / artefacts:** v1003 scan: `P2 Statische Dauereffekte` 808 sentences / 769 touched / 476 solo (`backend/data/exports/offene-fragmente-2026-11-19-v1003-vollpool-achsen.md`, `-gruppen.md`, `-zuordnung.jsonl`).
- **Known failures:** (none recorded)
- **Residue:** (none yet)

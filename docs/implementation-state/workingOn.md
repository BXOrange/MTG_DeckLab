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

## MEC-169 · Chosen-count sacrifice costs

- **Started / last update:** 2026-11-20 / 2026-11-20
- **Goal of this run:** close MEC-169: "sacrifice ~ and any number of (other <filter>) creatures" activation costs and "as an additional cost, sacrifice any number of creatures / an artifact or creature with mana value X" spell costs, with each sacrificed object recorded and read (Sword of the Ages, Vicious Betrayal, Emrakul's Evangel, Nahiri's Sacrifice).
- **Done:** (nothing yet)
- **In progress:** M1: verify what exists.
- **Next step:** the ticket text says only fixed counts exist, but `costs.py` already defines `SACRIFICE_COUNT_ANY` ("one or more") and `SACRIFICE_COUNT_X`: find their parser rows, payment and choice paths and why the four cards still fail (`understand_card`, `parser_probe`), then build only the missing piece (count announced by the player, "this way" count/total read from the `sacrificed` cost referents, filter "other non-Eldrazi", self-sacrifice plus the group, "then exile ~ and those creature cards", Nahiri's X = sacrificed MV).
- **Decisions:** (none yet)
- **Baselines / artefacts:** PARSER_VERSION 1018 at start.
- **Known failures:** (none recorded)
- **Residue:** (none yet)

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
- **Next step:** <the exact next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-320 · Edict counts, punishers and "if they can't" riders

- **Goal:** complete the entire recorded residue, then close, commit and push (user confirmed full scope).
- **Done:** original 38-case suite passes; shared count/fraction, punisher and unable-rider implementation retained. Coordinated edict sequences, optional filtered edicts, repeat, random discard and fractional additional costs implemented; gameplay validation underway.
- **In progress:** final full-cache suite and parser extraction; masked full-pool audit: +34 parser-modeled / +44 covered, zero losses; all 20 recorded residue cards now have bound implementations. Focused validation: 273 passed, including 101 PAR-320 cases (cost payment, choices/clone, control duration, exact graveyard visits, replacement and partial instructions).
- **Next step:** inspect full-cache/audit results, finish history and coverage/status documentation, extract the enlarged edict grammar into its own module, close tracking and push.
- **Baselines:** reconstructed committed v944 source in `/tmp/par320-base`, masked full-pool specs `/tmp/par320-base944.json`.
- **Known failures:** initial broad run found only stale handler-order and parser-version locks before being interrupted for implementation (6,264 passed).
- **Residue:** no recorded card implementation gaps; final full-cache verification, grammar extraction and documentation/commit remain.

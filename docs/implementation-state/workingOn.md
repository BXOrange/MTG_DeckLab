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

## ENG-65 · Interactive payment choice for alternative costs that return or sacrifice permanents

- **Started / last update:** 2026-11-20 / 2026-11-20
- **Goal of this run:** close ENG-65: the player chooses which permanents an alternative cost returns or sacrifices (RULE 118.9, 601.2b-h), then the parser rows for Thwart, Tidal Bore and Delraich.
- **Done:** (nothing yet)
- **In progress:** M1: replace the auto-pick in `_return_to_hand_count_candidates` / `_return_to_hand_candidate` / `_sacrifice_candidate` with a player choice.
- **Next step:** read how alternative costs are announced and paid (`game/costs.py`, `engine/casting_mixin.py`, the `_*_cost_choice` / `open_choice` pattern), add the choice for return and sacrifice costs, then widen `ALT_COST_RETURN_TWO_RE` and `sacrifice_count`.
- **Decisions:** no silent auto-pick when more than one legal payment exists; a single legal payment may be taken without asking only if that is the established convention for other costs in this engine (check first).
- **Baselines / artefacts:** PARSER_VERSION 1010 at start.
- **Known failures:** (none recorded)
- **Residue:** (none yet)

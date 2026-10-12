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

---

## PLAY-ALL · Make every saved deck playable

- **Goal:** Bring every non-cube saved deck to N/N and close all recorded correctness gaps; Commander Cube remains optional.
- **Next step:** Wire Burn Away's controller-graveyard body into the parser using the prepared untargeted event-controller variant of the existing exile effect, then continue the remaining parser axes below. Commit and push after successful tests; push approval remains pending.
- **Decisions:** Prefer deck-by-deck work and reusable primitives; hand-author isolated gaps. Alchemy is a permanent non-goal. MODELED/AUTHORED coverage alone does not prove rules-exact behavior.
- **Current validation:** All 41 saved decks have been rechecked after offline cache reseeding: every non-cube deck is N/N, with no unresolved names. Optional Commander Cube: 570/749. Last complete backend/full-cache validation: 12,930 passed (v625). The prepared Burn Away effect variant has two passing direct regressions, but its parser wiring and end-to-end card validation remain open.
- **Coverage baseline:** Current parser v625; authoritative measurement: 21,046/35,046 (60.1%), Commander-legal 20,271/32,068 (63.2%). Remeasure and synchronize CLAUDE.md, PARSER_LONG_TAIL.md and status.de/en.js after further parser changes.

### Remaining scope

- Dies-this-turn bodies: Burn Away, Reincarnation, Rushed Rebirth, Fatal Fissure's earthbend, Sandals of Abdallah / Initiate of Blood source-referencing bodies, Time to Feed.
- Broader mana-ability counter riders.
- Counter/pump-then-fight.
- Flicker with riders.
- Multi-event attack/block/target heads.
- Equipped-creature X pump.

Shared results belong in Done_Backend.md; individual-card behavior belongs in its implementation and tests. Remove this block only after all remaining scope is verified complete.

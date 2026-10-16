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

## PAR-156 · Counter or pump, then fight

- **Started / last update:** 2026-10-16 / 2026-10-16
- **Goal of this run:** Complete the connected buff/counter-before-fight family, including verified composite residue.
- **Done (built + tested):** Parser v663 shared sequences and linked/reflexive follow-ups support 17 previously uncovered paper-family cards; Ancient Animus was already authored, Algorithmic Ferocity is an explicit Alchemy non-goal. Directed fight receipts preserve actual excess/hit sets across replacement choices, clone/undo and concession. Conditions affect only the friendly bonus; permanent Host/Augment bonuses and original target groups are retained. Full backend --full-cache: 14,097 passed, 1 skipped (/tmp/par156-repaired-root-full.log); 61 family tests and 265 broader focused tests passed. Cache comparison +19/-0 includes two verified collateral cards.
- **In progress:** Verified backend milestone committed as e03178c7; MEC-123 delivery now completes Alexander at parser v664.
- **Next step:** Record the completed independent 20-card matrix audit and close PAR-156 in its own commit after MEC-123.
- **Decisions:** No silent scope reduction: Ace/Gimli/Kraul/Rhino/Fight for the Throne are delivered; Alexander stays explicit residue. Group effects survive source departure; only true self/fight instructions reject later source incarnations. One-sided source damage retains legal last-known information.
- **Baselines / artefacts:** Original v662 from f7ee7bdb reconstructed /tmp/par156-before.json; final v663 probe /tmp/par156-worker-probe.log. Authoritative v663 coverage 21,591/35,046 (61.6%); Commander 20,773/32,068 (64.8%). MEC-123 baseline /tmp/mec123-before.json.
- **Known failures:** None after repair and final full-cache run.
- **Residue:** Final close-out commit after completed independent matrix audit (103 focused tests passed; 19 paper cards supported, one explicit Alchemy non-goal). Combined full-cache gate: 14,141 passed, 1 skipped, plus all three proxy tests passed with local socket access.

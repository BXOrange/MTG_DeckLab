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

## PAR-149 · Combat timing, dying enchanted hosts and quoted emblems

- **Started / last update:** 2026-10-15 / 2026-10-16
- **Goal of this run:** Fully support all three named families, as explicitly selected by user.
- **Done (built + tested):** Combat cast windows, dying-host returns and recursive quoted emblems in c79ee918/882991b3; Dovin/stun/overlapping untap caps verified in browser. MEC-120 sideboard runtime (13260e9c) and MEC-121 real loss replacement (ea4a9129) delivered. Gift now validates host/Aura graveyard visits and returned-host battlefield incarnation, attaches legally before entry; 31 independent focused tests passed (/tmp/par149-gift-root-tests.log).
- **In progress:** Gift correction committed as 0d06818e after 31 independent tests. MEC-122 completed: authored Teferi simultaneous untap and turn-based opponent-step draws verified; full-cache suite 14,036 passed, 1 skipped.
- **Next step:** Finalize PAR-149 requirement matrix and durable documentation; full-cache proof /tmp/mec122-repaired-full.log covers final Gift and all three families, so close with a separate documentation commit.
- **Decisions:** Existing authored implementations count as actual family support when verified. Unrelated planeswalker clauses are independent blockers. No inert quoted-body markers.
- **Baselines / artefacts:** Original pre-family commit c3f48a03 reconstructed in isolation: parser v658, 21,515 covered. Current v662 probe: +57 / -0 versus that original baseline (/tmp/par149-final-original-diff.log). Authoritative coverage 21,572/35,046; /tmp/mec121-complete-full-cache.log: 14,005 passed, 1 skipped before Gift. Current audit plans /tmp/par149-teferi-plan.md and /tmp/par149-audit-runtime.py.
- **Known failures:** None after MEC-122 full-cache verification. Gift's verified stale-identity and illegal-entry bugs are corrected by meaningful regressions.
- **Residue:** Final family requirement audit and durable documentation/close-out commit. Three-family matrix /tmp/par149-family-audit.md and original658-to662 comparison (+57/-0) are complete. PAR-149 remains open until final closure.

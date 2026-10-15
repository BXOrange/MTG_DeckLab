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

- **Started / last update:** 2026-10-15 / 2026-10-15
- **Goal of this run:** Fully support all three families named in PAR-149; user explicitly selected all three.
- **Done (built + tested):** Integrated nondependency suite 286 passed (seven PAR-149 files, ISA and search grammar), plus emblem-body suite 36 passed including borrowed-host nested loyalty grants. Combat timing, dying hosts, quoted envelope, all nondependency emblem bodies and static permissions built with live gameplay tests; Chandra, Jaya, Ersta, Tezzeret animation and color/permanent search verified. Positive permanent-type search excludes Conspiracy.
- **In progress:** Reviewable partial milestone committed on user request before complete-suite verification. Root independently ran all six PAR-149 regression files: 185 passed (/tmp/par149-root-pre-isolation.log); generic-board browser smoke passed Dovin, stun and overlapping Winter Orb choices. Pre-commit probe: +56 newly covered, zero regressions; no authoritative coverage measurement yet.
- **Next step:** Run the full backend suite including --full-cache on this milestone; implement and commit MEC-120/121 separately, then finish PAR-149 integration, authoritative coverage/status updates and complete verification. No code stash is needed after the partial commit.
- **Decisions:** User requires all three named families. Other planeswalker abilities and unrelated timing phrasings are independent blockers. Sideboard and loss replacement remain fail-closed pending their real infrastructure.
- **Baselines / artefacts:** Parser bumped to v659 for the partial commit to invalidate old coverage rows; pre-edit snapshot /tmp/par149-baseline.json (v658, 21,515 covered names); emblem audit /tmp/par149-emblem-audit.json; latest audit /tmp/par149-emblem-final-nondependency.txt; final diff /tmp/par149-diff-final-nondependency.txt; browser logs /tmp/par149-dovin-browser.json and /tmp/par149-dovin-overlap-browser.json.
- **Known failures:** None in verified focused suites.
- **Residue:** Puresteel Angel loss-replacement emblem and Seek Bolas’s Counsel nonland-sideboard emblem depend on MEC-121/120. Other remaining card clauses (including Talent loyalty-counter draw trigger) are independent of the three named families. Full-suite/full-cache verification and authoritative coverage/status synchronization remain outstanding; this milestone does not close PAR-149.

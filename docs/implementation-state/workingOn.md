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
- **In progress:** Gift correction committed as 0d06818e after 31 independent tests. MEC-122 corrects authored Teferi simultaneous untap and turn-based opponent-step draws in disjoint files.
- **Next step:** Finish MEC-122, then independently audit all three families, compare original baseline/current coverage, synchronize durable documentation and close PAR-149 after full-cache verification.
- **Decisions:** Existing authored implementations count as actual family support when verified. Unrelated planeswalker clauses are independent blockers. No inert quoted-body markers.
- **Baselines / artefacts:** Original pre-family commit c3f48a03 reconstructed in isolation: parser v658, 21,515 covered. Current v662 probe: +57 / -0 versus that original baseline (/tmp/par149-final-original-diff.log). Authoritative coverage 21,572/35,046; /tmp/mec121-complete-full-cache.log: 14,005 passed, 1 skipped before Gift. Current audit plans /tmp/par149-teferi-plan.md and /tmp/par149-audit-runtime.py.
- **Known failures:** Authored Teferi timing remains pending MEC-122. Gift's verified stale-identity and illegal-entry bugs are corrected by meaningful regressions.
- **Residue:** MEC-122, final family/cache audit and full-cache validation with Gift; coverage/status documentation and final close-out commit. PAR-149 remains open.

## MEC-122 · Opponent draw-step turn-based actions

- **Started / last update:** 2026-10-16 / 2026-10-16
- **Goal of this run:** Source-scoped other-player draws during the draw-step turn-based action; correct Teferi, Who Slows the Sunset's draw and simultaneous untap emblem abilities.
- **Done (built + tested):** Source-scoped turn-based draw sequence, one instruction per emblem, active-first/APNAP, paused draw/mill replacements, Dredge/Miracle, cloned state/undo, controlled turns and concessions. Beginning/delayed triggers remain buffered until every draw finishes; SBAs and priority follow the complete sequence. Real Teferi loyalty emblem and Seedborn Muse now use the shared untap static; foreign untaps preserve own-step freeze flags and respect stun/phasing/Stasis. Parser v662; full-cache probe +0 / 0 regressions. Targeted engine/catalogue/session/replacement/ISA/version tests: 459 passed (/tmp/mec122-regression.log). Baseline ea4a9129 full-cache: 14,005 passed, 1 skipped.
- **In progress:** Checkpoint source reviewed by root; full-cache run completed with seven failures. Source is not ready for closure. Gift changes were kept separate. Delegated workers exhausted their usage allowance after handoff.
- **Next step:** Delegate integration repair when workers are available: inspect seven failures in /tmp/mec122-root-full.log, correct real regressions and outdated test assumptions without weakening coverage, rerun focused tests and full --full-cache, then synchronize coverage/status/docs and close with a separate commit.
- **Decisions:** One additional draw per applicable emblem copy. Reuse simultaneous untap static; do not model either action as a trigger. Finish all turn-based draws before trigger announcements/priority. Rules: 504.1 / 614 / 616.
- **Baselines / artefacts:** /tmp/par149-teferi-plan.md; /tmp/mec122-before.json; /tmp/mec122-diff.log; /tmp/mec122-regression.log; /tmp/mec122-coverage.{json,log}; isolated /tmp/mec122-coverage.sqlite.
- **Known failures:** Root full-cache: 14,027 passed, 1 skipped, 7 failed (/tmp/mec122-root-full.log): services/test_priority_yield.py starting-player skipped draw expectation; test_continuations.py dispatcher size 41 versus <40; test_cube_batch_b2.py Seedborn old UNTAP-trigger expectation; four test_omen_machine_family.py draw-step behaviors. Distinguish stale expectations from runtime regressions before changing tests.
- **Residue:** Seven full-suite failures, independent continuation/trigger review, green full-cache verification and final coverage/status/docs. Current isolated v662 coverage is 21,572/35,046 (61.6%); probe vs v661 +0/-0. Ticket remains open; checkpoint commit is not completion.
